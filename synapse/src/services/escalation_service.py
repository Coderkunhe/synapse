"""Escalation 服务 — O SLA 超时自动升级到 Human (P13-B9 · PFL-151 Option B)。

SPoF 梯度防御 B 线（Server 侧两阶段梯度响应）：
- Phase 1 (escalation_minutes=10): 创建 @Human 消息 + WS push + 记录 task.escalated 事件
- Phase 2 (revert_minutes=120): 委托给 ``detect_stale_verifications()`` 负责 auto-revert

从 ``stale_task_detector.py`` 提取为独立服务（P13-B9），满足 C9 验收标准：
``escalation_service.py``: O over escalation_minutes → ``POST /tasks/{id}/messages`` @Human + event 记录。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.constants import ActorType, EventType, TaskStatus
from src.models.event import Event
from src.models.task import Task
from src.services.event_store import event_store
from src.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)


async def detect_stale_verifications_escalation(
    db: AsyncSession,
    escalation_minutes: int = 10,
    revert_minutes: int = 120,
    cooldown_minutes: int = 30,
) -> dict:
    """扫描 in_verification 任务，超 escalation 阈值但未达 revert 阈值时升级到 Human。

    P13-B9 · PFL-151 Option B — SPoF 梯度防御 B 线。

    两阶段梯度响应：
    - Phase 1 (escalation_minutes): 创建 @Human 消息 + WS push + 记录 task.escalated 事件
    - Phase 2 (revert_minutes): 已有 detect_stale_verifications() 负责 auto-revert

    去重：检查同一 in_verification 周期内是否已升级过（通过 task.escalated 事件 +
    cooldown 窗口）。

    Args:
        db: 数据库会话。
        escalation_minutes: O 沉默多久后升级（默认 10 分钟）。
        revert_minutes: auto-revert 阈值——超过此阈值的任务不在此处理（交给 detect_stale_verifications）。
        cooldown_minutes: 同任务不重复升级的最小间隔。

    Returns:
        ``{"escalated_count": N, "escalated_task_ids": [...]}``。
    """
    from src.models.event import Event
    from src.services.conversation_service import create_message
    from src.services.event_store import event_store
    from src.services.ws_manager import ws_manager
    from src.models import ProjectActorRole

    now = datetime.now(timezone.utc)
    escalation_cutoff = now - timedelta(minutes=escalation_minutes)
    revert_cutoff = now - timedelta(minutes=revert_minutes)

    # 查找：in_verification 超过 escalation 阈值但未达 revert 阈值
    stmt = select(Task).options(selectinload(Task.project)).where(
        Task.status == TaskStatus.IN_VERIFICATION,
        Task.updated_at < escalation_cutoff,
        Task.updated_at >= revert_cutoff,
    )
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    escalated_ids: list[str] = []
    for task in candidates:
        team_id = task.project.team_id if task.project else ""

        # ── Dedup: 检查此次 in_verification 周期内是否已升级 ──
        cooldown_cutoff = now - timedelta(minutes=cooldown_minutes)
        prior_escalation = await db.execute(
            select(func.count(Event.id)).where(
                Event.event_type == EventType.TASK_ESCALATED,
                Event.target_type == "task",
                Event.target_id == task.id,
                Event.created_at >= cooldown_cutoff,
            )
        )
        if (prior_escalation.scalar() or 0) > 0:
            continue

        # ── 记录 escalation 事件 ──
        await event_store.record(
            db,
            event_type=EventType.TASK_ESCALATED,
            team_id=team_id,
            actor_type=ActorType.SYSTEM,
            actor_id="verification_escalation_detector",
            target_type="task",
            target_id=task.id,
            payload={
                "reason": "orchestrator_sla_timeout",
                "escalation_minutes": escalation_minutes,
                "task_status": task.status,
                "task_title": task.title,
            },
        )
        # B48: flush event 到 DB，使后续 create_message 失败不影响 event
        await db.flush()

        # ── 创建任务评论 @Human ──
        # B48: sender_worker_id="system" 可能因 FK 约束失败（worker 表无 "system"）。
        # 通过 savepoint 隔离——message 创建失败不阻断 escalation 事件记录。
        _task_id = task.id
        _task_title = task.title
        try:
            savepoint = await db.begin_nested()
            await create_message(
                db,
                task_id=_task_id,
                workflow_id=None,
                message_type="comment",
                body=(
                    f"@Human ⚠️ **Orchestrator SLA 超时 — 需要人工介入**\n\n"
                    f"- **Task**: {_task_title}\n"
                    f"- **状态**: 已等待 O 验收超过 {escalation_minutes} 分钟\n"
                    f"- **建议**: 请检查 O 是否在线，或手动验收此任务\n"
                    f"- **自动回退**: 如无人处理，系统将在 {revert_minutes} 分钟时自动回退"
                ),
                in_reply_to_id=None,
                sender_worker_id="system",
                team_id=team_id,
                actor_type=ActorType.SYSTEM,
                actor_id="verification_escalation_detector",
            )
            await savepoint.commit()
        except Exception:
            logger.warning(
                "Failed to create escalation message for task %s "
                "(escalation event still recorded)",
                _task_id,
                exc_info=True,
            )
            try:
                await savepoint.rollback()
            except Exception:
                pass

        # ── WS push 通知所有 Human + Orchestrator ──
        human_result = await db.execute(
            select(ProjectActorRole).where(
                ProjectActorRole.project_id == task.project_id,
                ProjectActorRole.role.in_(["admin", "lead", "orchestrator"]),
            )
        )
        human_roles = human_result.scalars().all()
        for hr in human_roles:
            await ws_manager.broadcast_to_actor(
                hr.worker_id,
                {
                    "type": "task.escalated",
                    "data": {
                        "task_id": task.id,
                        "task_title": task.title,
                        "reason": "orchestrator_sla_timeout",
                        "escalation_minutes": escalation_minutes,
                    },
                },
            )

        escalated_ids.append(task.id)

    return {
        "escalated_count": len(escalated_ids),
        "escalated_task_ids": escalated_ids,
    }
