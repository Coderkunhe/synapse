"""P10-B36: CircuitBreaker Service 测试 — 状态机 + check/record 操作."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.constants import (
    ActorType,
    CircuitBreakerStateEnum,
    CircuitBreakerTargetType,
)
from src.db import async_session_factory
from src.models.circuit_breaker import CircuitBreaker
from src.services.circuit_breaker_service import (
    L1_COOLDOWN_MINUTES,
    L1_FAILURE_THRESHOLD,
    L2_FAILURE_THRESHOLD,
    check,
    get_breaker,
    get_or_create_breaker,
    record_failure,
    record_success,
    reset_breaker,
)
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ══ Fixtures ══


@pytest_asyncio.fixture
async def db_session():
    """每个测试一个独立数据库会话，测试结束回滚."""
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def actor_info(seed):
    return {
        "team_id": seed.team_id,
        "actor_type": ActorType.WORKER,
        "actor_id": seed.worker_id,
    }


@pytest.fixture
def test_worker_id(seed):
    """使用 seed 中的 worker_id 作为测试目标."""
    return seed.worker_id


# ══ Get or Create ══


class TestGetOrCreateBreaker:
    async def test_get_or_create_creates_new(self, db_session, test_worker_id):
        """首次调用创建新熔断器记录."""
        breaker = await get_or_create_breaker(
            db_session,
            target_type=CircuitBreakerTargetType.WORKER,
            target_id=test_worker_id,
        )
        await db_session.commit()

        assert breaker.id.startswith("cb_")
        assert breaker.target_type == CircuitBreakerTargetType.WORKER
        assert breaker.target_id == test_worker_id
        assert breaker.state == CircuitBreakerStateEnum.CLOSED
        assert breaker.failure_count == 0

    async def test_get_or_create_idempotent(self, db_session, test_worker_id):
        """重复调用返回已有记录."""
        b1 = await get_or_create_breaker(
            db_session,
            target_type=CircuitBreakerTargetType.WORKER,
            target_id=test_worker_id,
        )
        await db_session.commit()

        b2 = await get_or_create_breaker(
            db_session,
            target_type=CircuitBreakerTargetType.WORKER,
            target_id=test_worker_id,
        )
        assert b2.id == b1.id
        assert b2.state == CircuitBreakerStateEnum.CLOSED

    async def test_different_targets_independent(self, db_session, seed):
        """不同 target 有独立的熔断器."""
        worker_a = seed.worker_id
        worker_b = generate_id("worker")

        b1 = await get_or_create_breaker(db_session, CircuitBreakerTargetType.WORKER, worker_a)
        b2 = await get_or_create_breaker(db_session, CircuitBreakerTargetType.WORKER, worker_b)

        assert b1.id != b2.id

    async def test_get_breaker_none(self, db_session):
        """不存在的熔断器返回 None."""
        result = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, "nonexistent")
        assert result is None


# ══ Check ══


class TestCheck:
    async def test_check_closed_returns_true(self, db_session, test_worker_id):
        """CLOSED 状态允许操作."""
        await get_or_create_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        allowed = await check(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert allowed is True

    async def test_check_no_breaker_returns_true(self, db_session):
        """无熔断器记录时默认允许."""
        allowed = await check(db_session, CircuitBreakerTargetType.WORKER, "nonexistent")
        assert allowed is True

    async def test_check_open_returns_false(self, db_session, test_worker_id):
        """OPEN 状态 + 冷却未到期 → 拒绝."""
        breaker = await get_or_create_breaker(
            db_session, CircuitBreakerTargetType.WORKER, test_worker_id
        )
        breaker.state = CircuitBreakerStateEnum.OPEN
        breaker.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        await db_session.commit()

        allowed = await check(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert allowed is False

    async def test_check_open_cooldown_expired_transitions_to_half_open(
        self, db_session, test_worker_id
    ):
        """OPEN 状态 + 冷却到期 → 自动转 HALF_OPEN + 允许."""
        breaker = await get_or_create_breaker(
            db_session, CircuitBreakerTargetType.WORKER, test_worker_id
        )
        breaker.state = CircuitBreakerStateEnum.OPEN
        breaker.cooldown_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db_session.commit()

        allowed = await check(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert allowed is True

        # 验证状态已转换
        await db_session.refresh(breaker)
        assert breaker.state == CircuitBreakerStateEnum.HALF_OPEN

    async def test_check_half_open_returns_true(self, db_session, test_worker_id):
        """HALF_OPEN 状态允许试探操作."""
        breaker = await get_or_create_breaker(
            db_session, CircuitBreakerTargetType.WORKER, test_worker_id
        )
        breaker.state = CircuitBreakerStateEnum.HALF_OPEN
        await db_session.commit()

        allowed = await check(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert allowed is True


# ══ Record Failure ══


class TestRecordFailure:
    async def test_record_failure_increments_count(self, db_session, test_worker_id):
        """记录失败增量 failure_count."""
        await record_failure(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        breaker = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert breaker.failure_count == 1
        assert breaker.last_failure_at is not None
        assert breaker.state == CircuitBreakerStateEnum.CLOSED  # 未达阈值

    async def test_record_failures_trigger_open(self, db_session, test_worker_id):
        """连续失败达阈值触发熔断 OPEN."""
        for i in range(L1_FAILURE_THRESHOLD):
            await record_failure(
                db_session, CircuitBreakerTargetType.WORKER, test_worker_id
            )

        breaker = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert breaker.state == CircuitBreakerStateEnum.OPEN
        assert breaker.failure_count == L1_FAILURE_THRESHOLD
        assert breaker.opened_at is not None
        assert breaker.cooldown_until is not None

    async def test_record_failure_records_event_on_open(self, db_session, test_worker_id):
        """熔断触发时记录 circuit_breaker.opened 事件."""
        for i in range(L1_FAILURE_THRESHOLD):
            await record_failure(
                db_session, CircuitBreakerTargetType.WORKER, test_worker_id
            )
        await db_session.commit()

        breaker = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)

        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "circuit_breaker",
                Event.target_id == breaker.id,
                Event.event_type == "circuit_breaker.opened",
            )
        )
        events = result.scalars().all()
        assert len(events) == 1

    async def test_record_failure_open_stays_open(self, db_session, test_worker_id):
        """已经是 OPEN 状态，再记录失败不改变状态."""
        for i in range(L1_FAILURE_THRESHOLD):
            await record_failure(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        breaker_before = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert breaker_before.state == CircuitBreakerStateEnum.OPEN

        # 再记录一次失败
        await record_failure(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        breaker_after = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert breaker_after.state == CircuitBreakerStateEnum.OPEN
        assert breaker_after.failure_count == L1_FAILURE_THRESHOLD + 1

    async def test_project_level_threshold(self, db_session, seed):
        """L2 Project 级熔断使用更大的阈值."""
        project_id = generate_id("project")
        for i in range(L2_FAILURE_THRESHOLD):
            await record_failure(db_session, CircuitBreakerTargetType.PROJECT, project_id)

        breaker = await get_breaker(db_session, CircuitBreakerTargetType.PROJECT, project_id)
        assert breaker.state == CircuitBreakerStateEnum.OPEN
        assert breaker.failure_count == L2_FAILURE_THRESHOLD


# ══ Record Success ══


class TestRecordSuccess:
    async def test_record_success_half_open_closes(self, db_session, test_worker_id):
        """HALF_OPEN 时成功 → CLOSED + 重置计数器."""
        # 先触发熔断
        for i in range(L1_FAILURE_THRESHOLD):
            await record_failure(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        # 冷却到期 → check 自动转 HALF_OPEN
        breaker = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        breaker.state = CircuitBreakerStateEnum.HALF_OPEN
        breaker.cooldown_until = None
        await db_session.commit()

        # 记录成功
        await record_success(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        breaker = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        assert breaker.state == CircuitBreakerStateEnum.CLOSED
        assert breaker.failure_count == 0
        assert breaker.last_failure_at is None
        assert breaker.opened_at is None
        assert breaker.cooldown_until is None

    async def test_record_success_records_event(self, db_session, test_worker_id):
        """HALF_OPEN→CLOSED 记录 circuit_breaker.closed 事件."""
        for i in range(L1_FAILURE_THRESHOLD):
            await record_failure(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        breaker = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        breaker.state = CircuitBreakerStateEnum.HALF_OPEN
        breaker.cooldown_until = None
        await db_session.commit()

        await record_success(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "circuit_breaker",
                Event.target_id == breaker.id,
                Event.event_type == "circuit_breaker.closed",
            )
        )
        events = result.scalars().all()
        assert len(events) == 1

    async def test_record_success_closed_noop(self, db_session, test_worker_id):
        """CLOSED 状态下成功不影响状态."""
        breaker = await get_or_create_breaker(
            db_session, CircuitBreakerTargetType.WORKER, test_worker_id
        )
        await db_session.commit()

        await record_success(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        await db_session.refresh(breaker)
        assert breaker.state == CircuitBreakerStateEnum.CLOSED

    async def test_record_success_no_breaker_creates_one(self, db_session, test_worker_id):
        """从未失败过的对象，记录成功时创建 CLOSED 记录."""
        result = await record_success(
            db_session, CircuitBreakerTargetType.WORKER, test_worker_id
        )
        await db_session.commit()

        assert result.state == CircuitBreakerStateEnum.CLOSED
        assert result.failure_count == 0


# ══ Reset Breaker ══


class TestResetBreaker:
    async def test_reset_open_to_closed(self, db_session, test_worker_id):
        """手动复位 OPEN → CLOSED."""
        for i in range(L1_FAILURE_THRESHOLD):
            await record_failure(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        breaker = await reset_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        assert breaker.state == CircuitBreakerStateEnum.CLOSED
        assert breaker.failure_count == 0
        assert breaker.opened_at is None
        assert breaker.cooldown_until is None

    async def test_reset_creates_if_not_exists(self, db_session, test_worker_id):
        """不存在的熔断器，reset 创建 CLOSED 记录."""
        breaker = await reset_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        assert breaker.state == CircuitBreakerStateEnum.CLOSED
        assert breaker.id.startswith("cb_")

    async def test_reset_records_event_with_override(self, db_session, test_worker_id):
        """手动复位记录 circuit_breaker.closed 事件含 override 标记."""
        for i in range(L1_FAILURE_THRESHOLD):
            await record_failure(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        breaker = await get_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await reset_breaker(db_session, CircuitBreakerTargetType.WORKER, test_worker_id)
        await db_session.commit()

        from src.models.event import Event
        import json as json_mod
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "circuit_breaker",
                Event.target_id == breaker.id,
                Event.event_type == "circuit_breaker.closed",
            ).order_by(Event.created_at.desc())
        )
        latest_event = result.scalars().first()
        assert latest_event is not None
        payload = json_mod.loads(latest_event.payload)
        assert payload.get("override") is True
