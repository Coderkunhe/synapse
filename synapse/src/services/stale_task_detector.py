"""Stale task 检测器 — 发现并标记长时间无更新的 in_progress 任务 (P11-B76)
+ verification 超时自动回收 (P11-B88) + READY task 无人认领检测 (P12-B25 · PFL-128)。

PFL-072 修复：Worker 可能遗弃 in_progress 任务（context 过期 / crash / token 耗尽），
Server 需要主动检测而非依赖 Agent 自报告。

PFL-077 修复：in_verification 任务等待 Human 验收超时 → 自动回退到 in_progress，
防止 O 崩溃/超时/卡住导致 Task 永久卡死在 in_verification。

PFL-128 修复：READY task 无自动恢复机制 — B23 狗粮发现 zombie Worker 阻断
O 匹配算法和 B pull fallback 后，READY task 永远无人认领。B24 模板层防御已落地，
本模块新增 Server 层安全网。

本模块提供扫描函数；调度由 main.py 后台任务 (_stale_task_reaper) 负责。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.constants import ActorType, EventType, TaskStatus
from src.models.event import Event
from src.models.task import Task
from src.services.event_store import event_store
from src.task_state_machine import apply_transition


async def detect_stale_tasks(
    db: AsyncSession,
    threshold_minutes: int = 60,
    reassign_threshold_minutes: int = 15,
) -> dict:
    """扫描 in_progress / paused 且 updated_at 超过阈值的任务。

    三层梯度响应（P11-B125）：
    ① 回收 — in_progress > reassign_threshold → unclaim → READY（可被重新认领）
    ② 告警 — 仅记录 ``task.stale_detected`` 事件供审计
    ③ 取消 — 超过 ``task_stale_max_detections`` 次 → CANCELLED

    PAUSED 任务不做 reassign（主动暂停≠被遗弃），维持原有检测+告警行为。

    Args:
        db: 数据库会话（调用方持有事务）。
        threshold_minutes: 无更新多久后视为 stale（默认 60 分钟）。
        reassign_threshold_minutes: 无更新多久后自动 unclaim→READY（默认 15 分钟）。

    Returns:
        ``{"stale_count": N, "stale_task_ids": [...],
           "cancelled_count": N, "cancelled_task_ids": [...],
           "reassigned_count": N, "reassigned_task_ids": [...],
           "reassigned_tasks": [...]}``。
    """
    now = datetime.now(timezone.utc)
    # P11-B125: 扫描窗口取两阈值较小者，确保 reassign 在配置的分钟数生效
    # 而非被 threshold_minutes（60min）延后。
    scan_window = min(threshold_minutes, reassign_threshold_minutes)
    cutoff = now - timedelta(minutes=scan_window)

    stmt = select(Task).options(selectinload(Task.project)).where(
        Task.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.PAUSED]),
        Task.updated_at < cutoff,
    )
    result = await db.execute(stmt)
    stale_tasks = result.scalars().all()

    max_detections = settings.task_stale_max_detections

    stale_ids: list[str] = []
    cancelled_ids: list[str] = []
    reassigned_ids: list[str] = []
    reassigned_tasks: list[dict[str, str | None]] = []
    for task in stale_tasks:
        team_id = task.project.team_id if task.project else ""

        # 反无限 stale 门禁 (P11-B108)：检查历史 stale 检测次数。
        # 超过阈值后不再只记录事件——直接 auto-cancel，打破
        # "永久 stale 但无人处理"的死循环。
        prior_detections = await db.execute(
            select(func.count(Event.id)).where(
                Event.event_type == "task.stale_detected",
                Event.target_type == "task",
                Event.target_id == task.id,
            )
        )
        detection_count = prior_detections.scalar() or 0

        if detection_count >= max_detections:
            # 达到最大检测次数 → 自动取消
            target_status = TaskStatus.CANCELLED
            event_type, payload = apply_transition(
                task,
                target_status,
                actor_type=ActorType.SYSTEM,
                actor_id="stale_task_detector",
                context={
                    "reason": "stale_max_detections_exceeded",
                    "stale_threshold_minutes": threshold_minutes,
                    "prior_stale_detection_count": detection_count,
                    "max_detections": max_detections,
                },
            )
            cancelled_ids.append(task.id)
        else:
            # P11-B125: 在"仅记日志"和"auto-cancel"之间加回收层
            # 如果 in_progress 任务超过 reassign_threshold → unclaim + READY
            updated = task.updated_at
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            stale_minutes = (
                (now - updated).total_seconds() / 60
                if updated is not None
                else float("inf")
            )
            if (
                task.status == TaskStatus.IN_PROGRESS
                and stale_minutes >= reassign_threshold_minutes
            ):
                # 回收：unclaim + 归还到 ready 池
                old_owner_type = task.owner_type
                old_owner_id = task.owner_id
                task.owner_type = None
                task.owner_id = None
                task.claimed_at = None
                target_status = TaskStatus.READY
                event_type, payload = apply_transition(
                    task,
                    target_status,
                    actor_type=ActorType.SYSTEM,
                    actor_id="stale_task_detector",
                    context={
                        "reason": "stale_reassign",
                        "stale_minutes": round(stale_minutes, 1),
                        "reassign_threshold_minutes": reassign_threshold_minutes,
                        "old_owner_type": old_owner_type,
                        "old_owner_id": old_owner_id,
                        "detection_count": detection_count + 1,
                    },
                )
                reassigned_ids.append(task.id)
                reassigned_tasks.append({
                    "task_id": task.id,
                    "old_owner_type": old_owner_type,
                    "old_owner_id": old_owner_id,
                })
            else:
                # 正常 stale 检测：仅记录事件
                event_type = "task.stale_detected"
                payload = {
                    "task_id": task.id,
                    "current_status": task.status,
                    "owner_type": task.owner_type,
                    "owner_id": task.owner_id,
                    "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                    "stale_threshold_minutes": threshold_minutes,
                    "detection_count": detection_count + 1,
                    "max_detections": max_detections,
                }
                stale_ids.append(task.id)

        await event_store.record(
            db,
            event_type=event_type,
            team_id=team_id,
            actor_type=ActorType.SYSTEM,
            actor_id="stale_task_detector",
            target_type="task",
            target_id=task.id,
            payload=payload,
        )

    return {
        "stale_count": len(stale_ids),
        "stale_task_ids": stale_ids,
        "cancelled_count": len(cancelled_ids),
        "cancelled_task_ids": cancelled_ids,
        "reassigned_count": len(reassigned_ids),
        "reassigned_task_ids": reassigned_ids,
        "reassigned_tasks": reassigned_tasks,
    }


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
        # B115 PFL-119: task.updated_at may be naive (SQLite DateTime), but
        # now is tz-aware. Make them consistent before subtraction.
        updated = task.updated_at
        if updated is not None and updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        seconds_stuck = int((now - updated).total_seconds())
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


async def detect_stale_verifications_escalation(
    db: AsyncSession,
    escalation_minutes: int = 10,
    revert_minutes: int = 120,
    cooldown_minutes: int = 30,
) -> dict:
    """扫描 in_verification 任务，超 escalation 阈值但未达 revert 阈值时升级到 Human。

    P12-B47 · PFL-151 Option B — O SLA 超时 auto-escalate。

    两阶段梯度响应：
    - Phase 1 (escalation_minutes): 创建 @Human 消息 + WS push + 记录 task.escalated 事件
    - Phase 2 (revert_minutes): 已有 detect_stale_verifications() 负责 auto-revert

    去重：检查同一 in_verification 周期内是否已升级过（通过 task.escalated 事件）。

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

        # ── 创建任务评论 @Human ──
        await create_message(
            db,
            task_id=task.id,
            workflow_id=None,
            message_type="comment",
            body=(
                f"@Human ⚠️ **Orchestrator SLA 超时 — 需要人工介入**\n\n"
                f"- **Task**: {task.title}\n"
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

        # ── WS push 通知所有 Human ──
        human_result = await db.execute(
            select(ProjectActorRole).where(
                ProjectActorRole.project_id == task.project_id,
                ProjectActorRole.role.in_(["admin", "lead"]),
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


async def detect_unclaimed_ready_tasks(
    db: AsyncSession,
    threshold_minutes: int = 30,
) -> dict:
    """扫描 READY 状态但长时间无人认领的任务（P12-B25 · PFL-128）。

    B23 狗粮发现：zombie Worker（session 退出但心跳 daemon 持续运行）会阻断
    O 匹配算法和 B pull fallback 两条认领路径，导致 READY task 永远无人认领。

    B24 已落地模板层防御（O-silence ``last_assignment_at``、zombie Worker
    防御行、Cap mismatch 上报），本函数是 Server 层安全网——检测并记录长时间
    无人认领的 READY task，通过 system_interventions 计数器暴露趋势。

    设计决策：
    - 不做 auto-reassign — READY task 的分配是 O 匹配算法的职责
    - 不做 task message 推送 — conversation_service 集成是后续优化
    - 仅记录事件 + 累加计数器 — 趋势上升 → God's-eye 调查根因

    Args:
        db: 数据库会话（调用方持有事务）。
        threshold_minutes: READY 多久无人认领视为异常（默认 30 分钟）。

    Returns:
        ``{"unclaimed_count": N, "unclaimed_task_ids": [...]}``。
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold_minutes)

    stmt = select(Task).options(selectinload(Task.project)).where(
        Task.status == TaskStatus.READY,
        Task.updated_at < cutoff,
    )
    result = await db.execute(stmt)
    unclaimed_tasks = result.scalars().all()

    unclaimed_ids: list[str] = []
    for task in unclaimed_tasks:
        team_id = task.project.team_id if task.project else ""

        updated = task.updated_at
        if updated is not None and updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        unclaimed_minutes = (
            (now - updated).total_seconds() / 60
            if updated is not None
            else float("inf")
        )

        await event_store.record(
            db,
            event_type="task.ready_unclaimed",
            team_id=team_id,
            actor_type=ActorType.SYSTEM,
            actor_id="stale_task_detector",
            target_type="task",
            target_id=task.id,
            payload={
                "task_id": task.id,
                "current_status": task.status,
                "unclaimed_minutes": round(unclaimed_minutes, 1),
                "threshold_minutes": threshold_minutes,
                "required_capabilities": task.required_capabilities,
            },
        )
        unclaimed_ids.append(task.id)

    return {
        "unclaimed_count": len(unclaimed_ids),
        "unclaimed_task_ids": unclaimed_ids,
    }
