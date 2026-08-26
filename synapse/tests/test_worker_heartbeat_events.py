"""P16-B6：心跳留痕 — worker.heartbeat 事件落库（服务集成测试，含数据库）。

背景：``Worker.last_heartbeat_at`` 是被覆盖的单值列，只记得「最后一跳」；
``EventType.WORKER_HEARTBEAT`` 虽在 ``src/constants.py`` 定义，但 ``src/`` 下
零引用 —— 心跳历史从未落库，「心跳次数 / 平均间隔」不可计算。

覆盖：
- 连续 3 次心跳 → 恰好 3 条 ``worker.heartbeat`` 事件，且 ``created_at`` 严格递增
- 事件的 actor / target / team / payload 字段正确
- 心跳事件与运行时状态转换事件并存（不互相替代）
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, EventType
from src.models.event import Event
from src.models.member import Member
from src.models.team import Team
from src.models.worker import Worker
from src.services.worker_service import (
    register_worker,
    worker_handshake,
    worker_heartbeat,
)
from src.utils.id_gen import derive_id, generate_id


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db(app) -> AsyncSession:
    """每个测试一个数据库 session，带 rollback。"""
    from src.db import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def seeded(db: AsyncSession) -> dict:
    """创建 Team + Member 以供 agent 注册。"""
    team_id = generate_id("team")
    member_id = generate_id("member")

    team = Team(id=team_id, name="HB Test Team", slug=f"hb-{team_id[-8:]}")
    member = Member(
        id=member_id, team_id=team_id, user_id="user-hb", display_name="Admin", role="admin"
    )
    db.add_all([team, member])
    await db.flush()
    return {"team_id": team_id, "member_id": member_id}


async def _register_and_handshake(db: AsyncSession, seeded: dict) -> Worker:
    """辅助函数：注册 agent 并执行握手 → 返回激活的 agent。"""
    agent, _ = await register_worker(
        db,
        team_id=seeded["team_id"],
        name="HB Worker",
        provider="claude",
        provider_model="sonnet",
        system_prompt=None,
        metadata=None,
        registered_by=None,
        actor_type="human",
        actor_id=derive_id(seeded["member_id"], "worker"),
    )
    await db.flush()

    agent = await worker_handshake(
        db,
        agent.id,
        worker_version="1.0.0",
        capabilities=[{"name": "code-review", "description": "Reviews code"}],
        supported_events=["task.claimed"],
        preferred_channel="websocket",
    )
    await db.flush()
    return agent


async def _heartbeat_events(db: AsyncSession, worker_id: str) -> list[Event]:
    """读取该 worker 的全部 worker.heartbeat 事件。"""
    result = await db.execute(
        select(Event).where(
            Event.event_type == EventType.WORKER_HEARTBEAT,
            Event.target_id == worker_id,
        )
    )
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════════════
# 服务集成测试
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestHeartbeatEventTrail:
    """每次成功心跳落一条不可变 Event —— 心跳历史可查、可聚合。"""

    async def test_three_heartbeats_record_three_events_increasing(
        self, db: AsyncSession, seeded: dict
    ):
        """连续 3 次心跳 → 3 条 worker.heartbeat 事件，created_at 严格递增。

        每轮心跳后立即比对新增事件（而非最后按 created_at 排序再断言），
        避免「先按 created_at 排序、再断言 created_at 递增」的循环论证。
        """
        agent = await _register_and_handshake(db, seeded)

        # 握手本身不应写入 heartbeat 事件（PFL-065 只更新时间戳列）
        assert await _heartbeat_events(db, agent.id) == []

        seen: set[str] = set()
        timestamps: list[datetime] = []

        for i in range(3):
            await worker_heartbeat(db, agent.id, current_load=i)
            await db.flush()

            events = await _heartbeat_events(db, agent.id)
            fresh = [e for e in events if e.id not in seen]
            assert len(fresh) == 1, (
                f"第 {i + 1} 次心跳应恰好新增 1 条 worker.heartbeat 事件，实际新增 {len(fresh)} 条"
            )
            seen.add(fresh[0].id)
            timestamps.append(fresh[0].created_at)

        assert len(seen) == 3, f"3 次心跳应留下 3 条独立事件，实际 {len(seen)} 条"

        for idx, (earlier, later) in enumerate(zip(timestamps, timestamps[1:])):
            assert later > earlier, (
                f"第 {idx + 1}→{idx + 2} 跳 created_at 应严格递增，实际 {earlier} → {later}"
            )

    async def test_heartbeat_event_fields(self, db: AsyncSession, seeded: dict):
        """事件的 actor / target / team / payload 字段正确。"""
        agent = await _register_and_handshake(db, seeded)

        await worker_heartbeat(db, agent.id, current_load=2, current_task_id="tsk-hb-1")
        await db.flush()

        events = await _heartbeat_events(db, agent.id)
        assert len(events) == 1
        event = events[0]

        assert event.event_type == EventType.WORKER_HEARTBEAT
        assert event.actor_type == ActorType.WORKER
        assert event.actor_id == agent.id
        assert event.target_type == "worker"
        assert event.target_id == agent.id
        assert event.team_id == seeded["team_id"]

        payload = json.loads(event.payload)
        assert payload["current_load"] == 2
        assert payload["active_task_id"] == "tsk-hb-1"

    async def test_heartbeat_event_coexists_with_runtime_transition(
        self, db: AsyncSession, seeded: dict
    ):
        """心跳事件与运行时转换事件并存 —— 新增留痕不吞掉既有状态事件。"""
        agent = await _register_and_handshake(db, seeded)

        worker, recovery_event = await worker_heartbeat(
            db, agent.id, current_load=1, current_task_id="tsk-hb-2"
        )
        await db.flush()

        # 心跳的返回契约不变：(worker, recovery_event_or_None)
        assert worker.id == agent.id
        assert recovery_event is None

        result = await db.execute(
            select(Event.event_type).where(Event.target_id == agent.id)
        )
        event_types = list(result.scalars().all())

        assert EventType.WORKER_HEARTBEAT in event_types
        assert EventType.WORKER_RUNTIME_BUSY in event_types, (
            f"IDLE→BUSY 转换事件应仍然写入，实际事件类型：{event_types}"
        )

    async def test_heartbeat_event_per_call_not_deduplicated(
        self, db: AsyncSession, seeded: dict
    ):
        """同一 worker 的重复心跳不做幂等合并 —— 每跳一条，才能算次数与间隔。"""
        agent = await _register_and_handshake(db, seeded)

        for _ in range(5):
            await worker_heartbeat(db, agent.id, current_load=0)
            await db.flush()

        events = await _heartbeat_events(db, agent.id)
        assert len(events) == 5, f"5 次心跳应留下 5 条事件，实际 {len(events)} 条"
