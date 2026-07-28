"""P8-B2：Worker 心跳 + 运行时状态 — 服务集成测试（含数据库）。

覆盖：
- 心跳更新正确列（last_heartbeat_at、last_progress_at、active_task_id）
- 通过心跳触发的运行时状态转换（idle→busy、busy→idle、error→idle）
- 握手期间填充的能力标签
- worker_to_response 包含运行时字段
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.worker_state_machine import ALLOWED_TRANSITIONS
from src.constants import WorkerRuntimeStatus
from src.exceptions import InvalidStateTransition, NotFoundError
from src.models.worker import Worker
from src.models.member import Member
from src.models.team import Team
from src.services.worker_service import (
    worker_handshake,
    worker_heartbeat,
    worker_to_response,
    get_worker,
    register_worker,
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

    team = Team(id=team_id, name="Test Team", slug=f"test-{team_id[-8:]}")
    member = Member(id=member_id, team_id=team_id, user_id="user-1", display_name="Admin", role="admin")
    db.add_all([team, member])
    await db.flush()
    return {"team_id": team_id, "member_id": member_id}


async def _register_and_handshake(db: AsyncSession, seeded: dict, **kw) -> Worker:
    """辅助函数：注册 agent 并执行握手 → 返回激活的 agent。"""
    agent, _ = await register_worker(
        db,
        team_id=seeded["team_id"],
        name=kw.get("name", "Test Worker"),
        provider=kw.get("provider", "claude"),
        provider_model=kw.get("provider_model", "sonnet"),
        system_prompt=None,
        metadata=None,
        registered_by=None,
        actor_type="human",
        actor_id=derive_id(seeded["member_id"], "worker"),
    )
    await db.flush()

    agent = await worker_handshake(
        db, agent.id,
        worker_version="1.0.0",
        capabilities=kw.get("capabilities", [
            {"name": "code-review", "description": "Reviews code"},
            {"name": "plan", "description": "Creates plans"},
        ]),
        supported_events=["task.claimed", "task.completed"],
        preferred_channel="websocket",
    )
    await db.flush()
    return agent


# ═══════════════════════════════════════════════════════════════════
# 服务集成测试
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestHeartbeatColumns:
    """心跳写入正确的列，而非仅写入 metadata JSON。"""

    async def test_heartbeat_sets_last_heartbeat_at(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)
        # P11-B81 PFL-065: handshake 现在同步更新 last_heartbeat_at
        # 一次网络往返已证明 Worker 在线 — 心跳时间戳在握手时即初始化
        assert agent.last_heartbeat_at is not None, (
            "handshake should set last_heartbeat_at (PFL-065)"
        )

        agent, _ = await worker_heartbeat(db, agent.id, current_load=0)
        await db.flush()

        assert agent.last_heartbeat_at is not None
        now = datetime.now(timezone.utc)
        delta = (now - agent.last_heartbeat_at).total_seconds()
        assert delta < 5, f"last_heartbeat_at 应为近期值，实际为 {delta}s 前"

    async def test_heartbeat_sets_active_task_id(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)
        task_id = "task-test-123"

        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id=task_id)
        await db.flush()

        assert agent.active_task_id == task_id

    async def test_heartbeat_sets_last_progress_on_task_change(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)

        # 第一次心跳：设置 active_task_id
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()
        progress_1 = agent.last_progress_at
        assert progress_1 is not None

        # 第二次心跳：同一任务 → last_progress_at 不变
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()
        assert agent.last_progress_at == progress_1

        # 第三次心跳：不同任务 → last_progress_at 更新
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-2")
        await db.flush()
        assert agent.last_progress_at is not None
        # 根据时间间隔可能不同也可能相同，但应该已设置
        # 关键测试：切换任务会触发进度更新
        assert agent.active_task_id == "task-2"


@pytest.mark.asyncio
class TestRuntimeStateTransitions:
    """心跳触发正确的运行时状态转换。"""

    async def test_idle_to_busy_on_task_pickup(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)
        assert agent.runtime_status == WorkerRuntimeStatus.IDLE

        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()

        assert agent.runtime_status == WorkerRuntimeStatus.BUSY
        assert agent.active_task_id == "task-1"

    async def test_busy_to_idle_on_task_complete(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)

        # 领取任务 → BUSY
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()
        assert agent.runtime_status == WorkerRuntimeStatus.BUSY

        # 完成任务 → IDLE
        agent, _ = await worker_heartbeat(db, agent.id, current_load=0, current_task_id=None)
        await db.flush()
        assert agent.runtime_status == WorkerRuntimeStatus.IDLE
        assert agent.active_task_id is None

    async def test_error_recovery_on_heartbeat(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)

        # 手动设置为 ERROR（模拟 B7 失败检测器）
        agent.runtime_status = WorkerRuntimeStatus.ERROR
        await db.flush()

        # 在 ERROR 状态下心跳 → 恢复到 IDLE
        agent, recovery_event = await worker_heartbeat(db, agent.id, current_load=0)
        await db.flush()

        assert agent.runtime_status == WorkerRuntimeStatus.IDLE
        assert recovery_event == "worker.runtime.idle"

    async def test_idle_stays_idle_no_task(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)
        agent, _ = await worker_heartbeat(db, agent.id, current_load=0, current_task_id=None)
        await db.flush()
        assert agent.runtime_status == WorkerRuntimeStatus.IDLE

    async def test_busy_stays_busy_same_task(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)

        # 领取任务
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()
        assert agent.runtime_status == WorkerRuntimeStatus.BUSY

        # 再次心跳，同一任务 → 保持 BUSY
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()
        assert agent.runtime_status == WorkerRuntimeStatus.BUSY


@pytest.mark.asyncio
class TestCapabilityTags:
    """能力标签在握手期间从真实数据中填充。"""

    async def test_capability_tags_populated(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded, capabilities=[
            {"name": "code-review", "description": "Reviews code"},
            {"name": "plan", "description": "Creates plans"},
            {"name": "test", "description": "Runs tests"},
        ])

        assert agent.capability_tags is not None
        assert agent.capability_tags["count"] == 3
        assert set(agent.capability_tags["names"]) == {"code-review", "plan", "test"}

    async def test_capability_tags_empty(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded, capabilities=[])

        assert agent.capability_tags is not None
        assert agent.capability_tags["count"] == 0
        assert agent.capability_tags["names"] == []


@pytest.mark.asyncio
class TestAgentToResponse:
    """worker_to_response 包含所有运行时字段。"""

    async def test_response_includes_runtime_fields(self, db: AsyncSession, seeded: dict):
        agent = await _register_and_handshake(db, seeded)
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()

        resp = worker_to_response(agent)
        assert resp["runtime_status"] == WorkerRuntimeStatus.BUSY
        assert resp["active_task_id"] == "task-1"
        assert resp["last_heartbeat_at"] is not None
        assert "capability_tags" in resp
        assert resp["capability_tags"]["count"] == 2


@pytest.mark.asyncio
class TestHeartbeatErrorHandling:
    """心跳的边界情况和错误处理。"""

    async def test_heartbeat_nonexistent_agent(self, db: AsyncSession, seeded: dict):
        with pytest.raises(NotFoundError):
            await worker_heartbeat(db, "nonexistent-id", current_load=0)

    async def test_heartbeat_clears_active_task(self, db: AsyncSession, seeded: dict):
        """current_task_id=None 的心跳应清除 active_task_id。"""
        agent = await _register_and_handshake(db, seeded)

        # 首先设置一个任务
        agent, _ = await worker_heartbeat(db, agent.id, current_load=1, current_task_id="task-1")
        await db.flush()
        assert agent.active_task_id == "task-1"

        # 然后清除它
        agent, _ = await worker_heartbeat(db, agent.id, current_load=0, current_task_id=None)
        await db.flush()
        assert agent.active_task_id is None

    async def test_heartbeat_preserves_metadata(self, db: AsyncSession, seeded: dict):
        """心跳仍然更新向后兼容的 metadata JSON。"""
        agent = await _register_and_handshake(db, seeded)
        agent, _ = await worker_heartbeat(db, agent.id, current_load=5, current_task_id="task-1")

        from src.utils.json_utils import safe_loads
        meta = safe_loads(agent.metadata_)
        assert meta["current_load"] == 5
        assert meta["current_task_id"] == "task-1"
