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
from src.utils.json_utils import safe_loads

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

        # ── P14-B8: 跳过 escalation 系统自创的 test task（阻断 G2 级联放大）──
        task_metadata = safe_loads(task.metadata_)
        if task_metadata and task_metadata.get("skip_escalation"):
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

        # ── P14-B2 G2: Auto-create PFL + Task ──
        await _maybe_auto_create_pfl_and_task(
            db=db,
            team_id=team_id,
            project_id=task.project_id,
            source_task_id=task.id,
            task_title=task.title,
            reason="orchestrator_sla_timeout",
            escalation_minutes=escalation_minutes,
        )

        escalated_ids.append(task.id)

    return {
        "escalated_count": len(escalated_ids),
        "escalated_task_ids": escalated_ids,
    }


async def _maybe_auto_create_pfl_and_task(
    db: AsyncSession,
    *,
    team_id: str,
    project_id: str,
    source_task_id: str,
    task_title: str,
    reason: str,
    escalation_minutes: int,
) -> None:
    """P14-B2 G2: 在 escalation 触发时自动创建 PFL 条目 + 跟踪 Task。

    所有异常静默捕获 — PFL/Task 创建失败不阻断 escalation 主流程。
    去重：检查同一 escalation 周期内是否已有 PFL 创建记录。
    """
    try:
        from src.services.pitfall_service import create_pitfall, pitfall_exists
        from src.services.task_create import create_task as _create_task_svc
        from src.constants import ActorType
        from src.config import settings

        # ── Feature flag ──
        if not settings.pfl_auto_create_enabled:
            return

        # ── Dedup: check for existing PFL in this escalation cycle ──
        # 使用 source_task_id + reason 作为去重键 — 同一 task 在同一 reason 下只创建一次
        pfl_title = f"[escalation] O SLA timeout — Task {source_task_id[:12]}"
        # 简化去重：检查 pitfalls.md 中是否有这个 source task 的 escalation PFL
        import re
        from src.services.pitfall_service import _get_pitfalls_path

        pitfalls_path = _get_pitfalls_path()
        if pitfalls_path.exists():
            content = pitfalls_path.read_text(encoding="utf-8")
            if f"source_task_id: {source_task_id}" in content and "orchestrator_sla_timeout" in content:
                return  # 已存在，跳过

        # ── Create PFL ──
        pfl_id = create_pitfall(
            title=pfl_title,
            description=(
                f"O 在 {escalation_minutes} 分钟内未验收 Task `{source_task_id}` "
                f"（{task_title}），系统自动升级。\n\n"
                f"- **source_task_id**: {source_task_id}\n"
                f"- **reason**: {reason}\n"
                f"- **escalation_minutes**: {escalation_minutes}"
            ),
            severity="🔴",
            cause=f"Orchestrator 在 {escalation_minutes} 分钟内未响应 verification",
            fix_direction=(
                "1. 检查 O Worker 是否在线\n"
                "2. 人工验收或重新分配 Task\n"
                "3. 根因分析后关闭此 PFL"
            ),
            discovery_source="P14-B2 自动登记（O SLA timeout escalation）",
        )

        # ── Create tracking Task ──
        escalation_task = await _create_task_svc(
            db,
            project_id=project_id,
            title=f"[{pfl_id}] O SLA 超时 — {task_title[:80]}",
            description=(
                f"## Escalation Task（自动创建 · P14-B2 G2）\n\n"
                f"- **来源**: O SLA timeout escalation\n"
                f"- **PFL**: {pfl_id}\n"
                f"- **源 Task**: `{source_task_id}` ({task_title})\n"
                f"- **超时阈值**: {escalation_minutes} 分钟\n"
                f"- **原因**: Orchestrator 未在 SLA 内验收\n\n"
                f"### 处理步骤\n\n"
                f"1. 检查 O Worker 是否在线\n"
                f"2. 人工验收源 Task 或重新分配\n"
                f"3. 关闭此 escalation Task"
            ),
            priority="p1",
            parent_task_id=None,
            batch_id=None,
            estimated_effort=None,
            tags=None,
            metadata={"skip_escalation": True},  # P14-B8: 阻断 G2 级联放大
            deadline_at=None,
            verifications=[],
            actor_type=ActorType.SYSTEM,
            actor_id="escalation_detector",
            team_id=team_id,
        )

        logger.info(
            "G2 auto-created PFL %s + Task %s for escalation on %s",
            pfl_id,
            escalation_task.id,
            source_task_id,
        )

    except Exception:
        logger.warning(
            "Failed to auto-create PFL+Task for escalation on task %s",
            source_task_id,
            exc_info=True,
        )
