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
from src.services.stale_task_detector import owner_is_alive
from src.constants import ActorType, TaskStatus
from src.task_state_machine import apply_transition


async def release_expired_leases(db: AsyncSession) -> dict:
    """扫描租约过期的任务并释放回 READY 状态。

    当 ``lease_expires_at < now`` 且任务仍处于 IN_PROGRESS
    （Worker 认领了但从未开始），通过状态机将任务转回 READY，
    供其他 Worker 认领。

    PFL-267 / PFL-245: 释放前先过 ``owner_is_alive`` 免死守卫 — 回收以
    「owner 是否失联」为准，不以「lease 是否过期」为准。卡在门禁但心跳仍新鲜的
    活 builder、以及 human/member owner（无续期机制）都不得被误释放。

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
        # PFL-267 / PFL-245: 活 owner 免死守卫 — 心跳仍新鲜的 owner worker 视为
        # 「活着但在干长活 / 卡在门禁」，human/member owner 无续期机制恒视为存活，
        # 跳过不释放。只有真失联才回收。
        if await owner_is_alive(db, task):
            continue

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

        # P16-B9 PFL-254: 租约回收后，若 Worker 的 active_task_id 还指着它，
        # 主动清空（此前白嫖「下次心跳会擦」这条已被 B5 删除的副作用）。
        from src.services.worker_scheduler import release_active_task
        await release_active_task(db, previous_owner_id, task.id)

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
