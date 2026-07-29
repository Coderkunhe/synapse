"""租约超时检测器 — 释放租约已过期的任务 (P8-B3)。

按 D5 B3：当 Worker 认领任务但在 T_lease（600s）内未开始工作时，
任务被释放回 READY 状态，供其他 Worker 认领。

本模块提供扫描函数；调度（后台任务、cron 触发器或端点触发）在 B7（失败处理）中接入。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import Task
from src.services.event_store import event_store
from src.constants import ActorType, TaskStatus
from src.task_state_machine import apply_transition


async def release_expired_leases(db: AsyncSession) -> dict:
    """扫描租约过期的任务并释放回 READY 状态。

    当 ``lease_expires_at < now`` 且任务仍处于 IN_PROGRESS
    （Worker 认领了但从未开始），通过状态机将任务转回 READY，
    供其他 Worker 认领。

    返回：
        ``{"released_count": N, "released_task_ids": [...]}``。
    """
    now = datetime.now(timezone.utc)

    stmt = select(Task).where(
        Task.lease_expires_at.isnot(None),
        Task.lease_expires_at < now,
        Task.status == TaskStatus.IN_PROGRESS,
    )
    result = await db.execute(stmt)
    expired = result.scalars().all()

    released_ids: list[str] = []
    for task in expired:
        previous_owner_id = task.owner_id

        # 通过状态机转回 READY
        event_type, payload = apply_transition(
            task, TaskStatus.READY,
            actor_type=ActorType.SYSTEM,
            actor_id="lease_detector",
            context={
                "reason": "lease_expired",
                "previous_owner_id": previous_owner_id,
            },
        )

        # 清除所有权追踪
        task.owner_type = None
        task.owner_id = None
        task.claimed_at = None
        task.lease_expires_at = None

        await event_store.record(
            db,
            event_type=event_type,
            team_id=None,  # 租约检测器跨团队；团队上下文来自任务
            actor_type=ActorType.SYSTEM,
            actor_id="lease_detector",
            target_type="task",
            target_id=task.id,
            payload=payload,
        )
        released_ids.append(task.id)

    return {"released_count": len(released_ids), "released_task_ids": released_ids}
