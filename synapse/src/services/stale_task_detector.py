"""Stale task 检测器 — 发现并标记长时间无更新的 in_progress 任务 (P11-B76)
+ verification 超时自动回收 (P11-B88)。

PFL-072 修复：Worker 可能遗弃 in_progress 任务（context 过期 / crash / token 耗尽），
Server 需要主动检测而非依赖 Agent 自报告。

PFL-077 修复：in_verification 任务等待 Human 验收超时 → 自动回退到 in_progress，
防止 O 崩溃/超时/卡住导致 Task 永久卡死在 in_verification。

本模块提供扫描函数；调度由 main.py 后台任务 (_stale_task_reaper) 负责。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.constants import ActorType, TaskStatus
from src.models.event import Event
from src.models.task import Task
from src.services.event_store import event_store
from src.task_state_machine import apply_transition


async def detect_stale_tasks(
    db: AsyncSession,
    threshold_minutes: int = 60,
) -> dict:
    """扫描 in_progress / paused 且 updated_at 超过阈值的任务，记录 stale 事件。

    检测到 stale task 后记录 ``task.stale_detected`` 事件供审计。
    不改变 Task 状态 — 保留现场给 Orchestrator 判断。

    覆盖 PAUSED 状态（P11-B90）：PAUSED 任务若无 Worker 恢复，
    永久卡死在暂停态，Server 需检测并告警。

    Args:
        db: 数据库会话（调用方持有事务）。
        threshold_minutes: 无更新多久后视为 stale（默认 60 分钟）。

    Returns:
        ``{"stale_count": N, "stale_task_ids": [...]}``。
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold_minutes)

    stmt = select(Task).options(selectinload(Task.project)).where(
        Task.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.PAUSED]),
        Task.updated_at < cutoff,
    )
    result = await db.execute(stmt)
    stale_tasks = result.scalars().all()

    stale_ids: list[str] = []
    for task in stale_tasks:
        team_id = task.project.team_id if task.project else ""
        await event_store.record(
            db,
            event_type="task.stale_detected",
            team_id=team_id,
            actor_type=ActorType.SYSTEM,
            actor_id="stale_task_detector",
            target_type="task",
            target_id=task.id,
            payload={
                "task_id": task.id,
                "current_status": task.status,
                "owner_type": task.owner_type,
                "owner_id": task.owner_id,
                "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                "stale_threshold_minutes": threshold_minutes,
            },
        )
        stale_ids.append(task.id)

    return {"stale_count": len(stale_ids), "stale_task_ids": stale_ids}


async def detect_stale_verifications(
    db: AsyncSession,
    threshold_minutes: int = 30,
) -> dict:
    """扫描 in_verification 且 updated_at 超过阈值的任务，自动回退到 in_progress。

    PFL-077 修复：in_verification 任务等待 Human 验收超时 → 通过状态机
    自动回退到 in_progress。防止 O 崩溃/超时/卡住导致 Task 永久卡死在
    in_verification，backlog 冻结。

    反 ping-pong 门禁（B88 补充）：同一任务被 auto-revert 次数达到
    ``verification_max_auto_reverts``（默认 3 次）后，不再回退，直接
    auto-cancel——打破"回退→重submit→再超时→再回退"的无限循环。

    回退后任务回到 Builder 的 in_progress 队列，Builder 可重新提交。
    Orchestrator 在监工循环中检测到回退事件后应优先重新验收或重新分配。

    Args:
        db: 数据库会话（调用方持有事务）。
        threshold_minutes: 无更新多久后视为超时（默认 30 分钟）。

    Returns:
        ``{"reverted_count": N, "reverted_task_ids": [...],
           "cancelled_count": N, "cancelled_task_ids": [...]}``。
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold_minutes)

    stmt = select(Task).options(selectinload(Task.project)).where(
        Task.status == TaskStatus.IN_VERIFICATION,
        Task.updated_at < cutoff,
    )
    result = await db.execute(stmt)
    stale_tasks = result.scalars().all()

    max_reverts = settings.verification_max_auto_reverts

    reverted_ids: list[str] = []
    cancelled_ids: list[str] = []
    for task in stale_tasks:
        seconds_stuck = int((now - task.updated_at).total_seconds())
        team_id = task.project.team_id if task.project else ""

        # 反 ping-pong 门禁：检查历史回退次数，超过阈值 → auto-cancel。
        # 计数器统计 Task 生命周期内所有 verification_timeout_reverted 事件，
        # 永不重置。此设计基于一个架构假设：Task 进入终态（COMPLETED/CANCELLED）
        # 后不可逆，因此不会出现"一个 Task 在不同时期反复进入 verification"的场景。
        # 如果未来引入"重新打开已完成 Task"功能，需要加时间窗口衰减。
        prior_reverts = await db.execute(
            select(func.count(Event.id)).where(
                Event.event_type == "task.verification_timeout_reverted",
                Event.target_type == "task",
                Event.target_id == task.id,
            )
        )
        revert_count = prior_reverts.scalar() or 0

        if revert_count >= max_reverts:
            # 达到最大回退次数 → 直接取消，打破无限 ping-pong 循环
            target_status = TaskStatus.CANCELLED
            ctx = {
                "reason": "verification_timeout_max_reverts_exceeded",
                "stale_threshold_minutes": threshold_minutes,
                "seconds_in_verification": seconds_stuck,
                "prior_auto_revert_count": revert_count,
                "max_auto_reverts": max_reverts,
            }
        else:
            # 正常回退到 in_progress
            target_status = TaskStatus.IN_PROGRESS
            ctx = {
                "reason": "verification_timeout",
                "stale_threshold_minutes": threshold_minutes,
                "seconds_in_verification": seconds_stuck,
                "auto_revert_count": revert_count + 1,
                "max_auto_reverts": max_reverts,
            }

        event_type, payload = apply_transition(
            task,
            target_status,
            actor_type=ActorType.SYSTEM,
            actor_id="verification_timeout_detector",
            context=ctx,
        )

        await event_store.record(
            db,
            event_type=event_type,
            team_id=team_id,
            actor_type=ActorType.SYSTEM,
            actor_id="verification_timeout_detector",
            target_type="task",
            target_id=task.id,
            payload=payload,
        )

        if target_status == TaskStatus.CANCELLED:
            cancelled_ids.append(task.id)
        else:
            reverted_ids.append(task.id)

    return {
        "reverted_count": len(reverted_ids),
        "reverted_task_ids": reverted_ids,
        "cancelled_count": len(cancelled_ids),
        "cancelled_task_ids": cancelled_ids,
    }
