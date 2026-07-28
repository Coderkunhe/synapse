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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, TaskStatus
from src.models.task import Task
from src.services.event_store import event_store
from src.task_state_machine import apply_transition


async def detect_stale_tasks(
    db: AsyncSession,
    threshold_minutes: int = 60,
) -> dict:
    """扫描 in_progress 且 updated_at 超过阈值的任务，记录 stale 事件。

    检测到 stale task 后记录 ``task.stale_detected`` 事件供审计。
    不改变 Task 状态 — 保留现场给 Orchestrator 判断。

    Args:
        db: 数据库会话（调用方持有事务）。
        threshold_minutes: 无更新多久后视为 stale（默认 60 分钟）。

    Returns:
        ``{"stale_count": N, "stale_task_ids": [...]}``。
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold_minutes)

    stmt = select(Task).where(
        Task.status == TaskStatus.IN_PROGRESS,
        Task.updated_at < cutoff,
    )
    result = await db.execute(stmt)
    stale_tasks = result.scalars().all()

    stale_ids: list[str] = []
    for task in stale_tasks:
        await event_store.record(
            db,
            event_type="task.stale_detected",
            team_id="",  # 跨 team 扫描；team 上下文来自 task
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

    回退后任务回到 Builder 的 in_progress 队列，Builder 可重新提交。
    Orchestrator 在监工循环中检测到回退事件后应优先重新验收或重新分配。

    Args:
        db: 数据库会话（调用方持有事务）。
        threshold_minutes: 无更新多久后视为超时（默认 30 分钟）。

    Returns:
        ``{"reverted_count": N, "reverted_task_ids": [...]}``。
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold_minutes)

    stmt = select(Task).where(
        Task.status == TaskStatus.IN_VERIFICATION,
        Task.updated_at < cutoff,
    )
    result = await db.execute(stmt)
    stale_tasks = result.scalars().all()

    reverted_ids: list[str] = []
    for task in stale_tasks:
        seconds_stuck = int((now - task.updated_at).total_seconds())

        # 通过状态机回退到 in_progress
        event_type, payload = apply_transition(
            task,
            TaskStatus.IN_PROGRESS,
            actor_type=ActorType.SYSTEM,
            actor_id="verification_timeout_detector",
            context={
                "reason": "verification_timeout",
                "stale_threshold_minutes": threshold_minutes,
                "seconds_in_verification": seconds_stuck,
            },
        )

        await event_store.record(
            db,
            event_type=event_type,
            team_id="",  # 跨 team 扫描；team 上下文来自 task
            actor_type=ActorType.SYSTEM,
            actor_id="verification_timeout_detector",
            target_type="task",
            target_id=task.id,
            payload=payload,
        )
        reverted_ids.append(task.id)

    return {"reverted_count": len(reverted_ids), "reverted_task_ids": reverted_ids}
