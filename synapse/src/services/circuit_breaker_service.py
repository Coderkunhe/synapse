"""熔断器 Service — CircuitBreaker 状态机 + check/record 操作。

P10-B36: 议题 ⑥ Service 层 — 熔断器状态机 Service。

三层熔断架构：
- L1 Worker 级: target_type=worker, 5 次连续失败 → OPEN, cooldown 30min
- L2 Project 级: target_type=project, 10 次失败 → OPEN, cooldown 60min
- L3 全局级: 远期（不在本表建模）

状态机: CLOSED → OPEN → HALF_OPEN → CLOSED

调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    ActorType,
    CircuitBreakerStateEnum,
    CircuitBreakerTargetType,
    EventType,
)
from src.exceptions import NotFoundError
from src.models.circuit_breaker import CircuitBreaker
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ── 阈值常量 ───────────────────────────────────────────────────────

# L1 Worker 级熔断
L1_FAILURE_THRESHOLD = 5       # 连续失败次数阈值
L1_COOLDOWN_MINUTES = 30       # 冷却时间（分钟）

# L2 Project 级熔断
L2_FAILURE_THRESHOLD = 10      # 失败次数阈值
L2_COOLDOWN_MINUTES = 60       # 冷却时间（分钟）


# ── 私有辅助 ──────────────────────────────────────────────────────


def _threshold_for(target_type: str) -> int:
    """返回目标类型对应的失败阈值。"""
    if target_type == CircuitBreakerTargetType.PROJECT:
        return L2_FAILURE_THRESHOLD
    return L1_FAILURE_THRESHOLD


def _cooldown_minutes_for(target_type: str) -> int:
    """返回目标类型对应的冷却时间（分钟）。"""
    if target_type == CircuitBreakerTargetType.PROJECT:
        return L2_COOLDOWN_MINUTES
    return L1_COOLDOWN_MINUTES


# ── 查询 / 幂等创建 ──────────────────────────────────────────────


async def get_breaker(
    db: AsyncSession,
    target_type: str,
    target_id: str,
) -> CircuitBreaker | None:
    """按 (target_type, target_id) 查找熔断器，不存在返回 None。"""
    result = await db.execute(
        select(CircuitBreaker).where(
            CircuitBreaker.target_type == target_type,
            CircuitBreaker.target_id == target_id,
        )
    )
    return result.scalar_one_or_none()


async def get_or_create_breaker(
    db: AsyncSession,
    target_type: str,
    target_id: str,
) -> CircuitBreaker:
    """幂等获取或创建熔断器记录。

    首次访问时自动创建 CLOSED 状态的记录。
    后续访问返回已有记录。
    """
    breaker = await get_breaker(db, target_type, target_id)
    if breaker is not None:
        return breaker

    breaker = CircuitBreaker(
        id=generate_id("circuit_breaker"),
        target_type=target_type,
        target_id=target_id,
        state=CircuitBreakerStateEnum.CLOSED,
        failure_count=0,
    )
    db.add(breaker)
    await db.flush()
    return breaker


# ── 状态机核心 ────────────────────────────────────────────────────


async def check(
    db: AsyncSession,
    target_type: str,
    target_id: str,
) -> bool:
    """检查熔断器是否允许操作。

    返回 True = 允许，False = 熔断中（拒绝）。

    状态逻辑：
    - CLOSED → 允许
    - HALF_OPEN → 允许（试探操作）
    - OPEN 且冷却未到期 → 拒绝
    - OPEN 且冷却已到期 → 自动转 HALF_OPEN → 允许
    """
    breaker = await get_breaker(db, target_type, target_id)
    if breaker is None:
        # 无熔断器记录 → 默认允许
        return True

    now = datetime.now(timezone.utc)

    if breaker.state == CircuitBreakerStateEnum.CLOSED:
        return True

    if breaker.state == CircuitBreakerStateEnum.HALF_OPEN:
        return True

    # OPEN 状态 — 检查冷却是否到期
    if breaker.state == CircuitBreakerStateEnum.OPEN:
        if breaker.cooldown_until is not None and now >= breaker.cooldown_until:
            # 冷却到期 → 自动转 HALF_OPEN
            breaker.state = CircuitBreakerStateEnum.HALF_OPEN
            await db.flush()
            return True
        return False

    # 未知状态 → 保守放行
    return True


async def record_failure(
    db: AsyncSession,
    target_type: str,
    target_id: str,
) -> CircuitBreaker:
    """记录失败事件 — 增量 failure_count，达阈值触发熔断。

    状态转换：
    - CLOSED/HALF_OPEN + failure_count < threshold → 增量计数，保持当前状态
    - CLOSED/HALF_OPEN + failure_count >= threshold → OPEN + event
    - 已经是 OPEN → 仅增量计数（不改状态）

    返回更新后的熔断器记录。
    """
    breaker = await get_or_create_breaker(db, target_type, target_id)
    threshold = _threshold_for(target_type)
    now = datetime.now(timezone.utc)

    breaker.failure_count += 1
    breaker.last_failure_at = now

    if breaker.state != CircuitBreakerStateEnum.OPEN:
        if breaker.failure_count >= threshold:
            # 触发熔断
            previous_state = breaker.state
            cooldown_minutes = _cooldown_minutes_for(target_type)
            breaker.state = CircuitBreakerStateEnum.OPEN
            breaker.opened_at = now
            breaker.cooldown_until = now + timedelta(minutes=cooldown_minutes)

            await db.flush()

            await event_store.record(
                db,
                event_type=EventType.CIRCUIT_BREAKER_OPENED,
                team_id="",  # 系统级事件
                actor_type=ActorType.SYSTEM,
                actor_id="circuit_breaker",
                target_type="circuit_breaker",
                target_id=breaker.id,
                payload={
                    "breaker_id": breaker.id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "previous_state": previous_state,
                    "new_state": CircuitBreakerStateEnum.OPEN,
                    "failure_count": breaker.failure_count,
                    "threshold": threshold,
                    "cooldown_until": breaker.cooldown_until.isoformat() if breaker.cooldown_until else None,
                },
            )

    await db.flush()
    return breaker


async def record_success(
    db: AsyncSession,
    target_type: str,
    target_id: str,
) -> CircuitBreaker:
    """记录成功事件 — HALF_OPEN 时成功则闭合熔断器。

    状态转换：
    - HALF_OPEN → CLOSED（重置 failure_count）+ event
    - CLOSED/OPEN → 不影响状态（CLOSED 时不需要记录成功；OPEN 时成功不应发生）

    返回更新后的熔断器记录。
    """
    breaker = await get_breaker(db, target_type, target_id)
    if breaker is None:
        # 无熔断器记录 → 不需要记录成功（从未失败过）
        breaker = await get_or_create_breaker(db, target_type, target_id)
        return breaker

    if breaker.state == CircuitBreakerStateEnum.HALF_OPEN:
        # 试探成功 → 闭合熔断器
        previous_state = breaker.state
        breaker.state = CircuitBreakerStateEnum.CLOSED
        breaker.failure_count = 0
        breaker.last_failure_at = None
        breaker.opened_at = None
        breaker.cooldown_until = None

        await db.flush()

        await event_store.record(
            db,
            event_type=EventType.CIRCUIT_BREAKER_CLOSED,
            team_id="",  # 系统级事件
            actor_type=ActorType.SYSTEM,
            actor_id="circuit_breaker",
            target_type="circuit_breaker",
            target_id=breaker.id,
            payload={
                "breaker_id": breaker.id,
                "target_type": target_type,
                "target_id": target_id,
                "previous_state": previous_state,
                "new_state": CircuitBreakerStateEnum.CLOSED,
            },
        )

    # CLOSED 状态下成功 — 静默，不记录事件
    # OPEN 状态下成功 — 理论上不应发生（check 会拒绝），但静默处理

    await db.flush()
    return breaker


async def reset_breaker(
    db: AsyncSession,
    target_type: str,
    target_id: str,
) -> CircuitBreaker:
    """管理员手动复位熔断器 → CLOSED + 清零计数器。

    无论当前状态如何，强制复位为 CLOSED。
    记录 CIRCUIT_BREAKER_CLOSED 事件（含 override 标记）。
    """
    breaker = await get_or_create_breaker(db, target_type, target_id)
    previous_state = breaker.state

    breaker.state = CircuitBreakerStateEnum.CLOSED
    breaker.failure_count = 0
    breaker.last_failure_at = None
    breaker.opened_at = None
    breaker.cooldown_until = None

    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.CIRCUIT_BREAKER_CLOSED,
        team_id="",  # 系统级事件
        actor_type=ActorType.SYSTEM,
        actor_id="circuit_breaker",
        target_type="circuit_breaker",
        target_id=breaker.id,
        payload={
            "breaker_id": breaker.id,
            "target_type": target_type,
            "target_id": target_id,
            "previous_state": previous_state,
            "new_state": CircuitBreakerStateEnum.CLOSED,
            "override": True,  # 标记为手动复位
            "reason": "manual_reset",
        },
    )

    return breaker
