"""故障检测器 — 统一故障检测 + 阻塞报告 (P8-B7)。

四条检测线（按 D5 B7）：
  1. 心跳超时（硬故障）：Worker last_heartbeat_at > T_HB → ERROR + 释放任务
  2. 进度超时（软故障）：Worker last_progress_at > T_PROG → ERROR + 释放任务
  3. 租约过期：委托给 lease_detector.release_expired_leases()
  4. 审核超时：Task IN_VERIFICATION > T_REVIEW → 仅 WS 通知

接线状态（P100-B158 定性收口 · PFL-267/PFL-262）：
  - 租约线（lease）         ✅ 已接后台循环（main._stale_task_reaper · B157）。
  - 心跳线（heartbeat）     manual-only by design — 非死代码。与
                            _worker_heartbeat_monitor 的 OFFLINE 语义重叠，
                            且 ERROR/OFFLINE + failure_count 语义统一是独立议题。
  - 进度线（progress）      manual-only by design — 非死代码。PFL-262 定调
                            「回收以 worker 是否失联为准，不以 task 是否有进度为准」；
                            last_progress_at 是「task 启动/切换时间」非真实进度，
                            自动接线会误伤 >T_PROG 的合法长任务（PFL-245/262 同族）。
  - 审核线（review）        仅 WS 通知，与 _stale_task_reaper 的
                            detect_stale_verifications 重叠（自动路径已有）。
  心跳/进度两条线仅由 admin 手动端点 POST /failure-detection/run 触发。

同时提供 ``report_blocker()`` 用于 Worker 提交阻塞报告。

所有操作在调用方的 DB 事务中执行 — 本模块不提交。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from src.worker_state_machine import apply_transition as worker_apply_transition
from src.constants import ActorType, OwnerType, WorkerRuntimeStatus, WorkerStatus, TaskStatus
from src.exceptions import ConflictError, ForbiddenError, NotFoundError
from src.models.worker import Worker
from src.models.task import Task
from src.constants import TaskStatus
from src.services.event_store import event_store
from src.services.provider_config_service import get_provider_heartbeat_timeout
from src.task_state_machine import apply_transition as task_apply_transition

# ── P8-B7 阈值 (D-P7-019, MVP 硬编码) ───────────────────

T_HB = 60          # 心跳超时 → 硬故障（秒）— 仅作为 fallback，优先使用 provider-aware timeout
T_PROG = 300       # 进度超时 → 软故障（秒）
T_REVIEW = 86400   # 审核超时 → 仅通知（秒，24h）
N_RETRY = 3        # 自动重试上限，超出后升级

# P12-B45 (PFL-144): provider-aware heartbeat timeout defaults
# Codex CLI 无 daemon，CronCreate-based heartbeat 间隔更长
T_HB_STANDARD = 300   # 5 min (persistent Workers: Claude Code daemon)
T_HB_CODEX = 1800     # 30 min (Codex CLI: no daemon, CronCreate-based)


# ── 心跳 / 进度检测 ────────────────────────────────────

async def detect_heartbeat_failures(
    db: AsyncSession,
    standard_timeout: int | None = None,
    codex_timeout: int | None = None,
) -> dict:
    """扫描心跳超时的 Worker 并将其转为 ERROR 状态。

    P12-B45 (PFL-144): provider-aware timeout — 通过
    ``get_provider_heartbeat_timeout(worker.provider)`` 从 Provider 配置注册中心
    获取超时阈值，替代 ``if worker.provider == "codex"`` 硬编码分支。

    P13-B9: 去硬编码 — B4 设计原则 #3 落地。

    Worker 被视为"硬故障"当：
      - status == "active" or "pending"（P12-B45: 扩展扫描范围）
      - runtime_status != "error"（已故障的 Worker 跳过）
      - last_heartbeat_at 已设置且距今超过 provider-specific timeout
      - last_heartbeat_at 为 None 且 Worker 注册距今超过 standard_timeout（从未发送心跳）

    故障 Worker 拥有的所有任务被释放回 READY。

    ⚠️ manual-only by design — 见模块 docstring「接线状态」（P100-B158）。
    """
    now = datetime.now(timezone.utc)

    # 查找心跳过期或从未心跳但注册时间很久的 Worker
    # P12-B45: 扩展扫描到 PENDING — Codex Worker 可能在 PENDING 状态发送心跳
    stmt = select(Worker).where(
        Worker.status.in_([WorkerStatus.ACTIVE, WorkerStatus.PENDING]),
        Worker.runtime_status != WorkerRuntimeStatus.ERROR,
    )
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    failed_worker_ids: list[str] = []
    released_task_ids: list[str] = []

    for worker in candidates:
        # P13-B9: provider-aware timeout via config registry (B4 原则 #3)
        # 显式参数覆盖仅用于测试兼容 — 任一参数非 None 即走旧逻辑
        if standard_timeout is not None or codex_timeout is not None:
            _std = standard_timeout if standard_timeout is not None else T_HB_STANDARD
            _cdx = codex_timeout if codex_timeout is not None else T_HB_CODEX
            timeout = _cdx if worker.provider == "codex" else _std
        else:
            timeout = get_provider_heartbeat_timeout(worker.provider)
        hb_cutoff = now - timedelta(seconds=timeout)
        registration_cutoff = now - timedelta(seconds=timeout)

        # SQLite 存储无时区信息的 datetime；归一化以便比较
        hb_cutoff_naive = hb_cutoff.replace(tzinfo=None)
        registration_cutoff_naive = registration_cutoff.replace(tzinfo=None)

        is_stale = False
        if worker.last_heartbeat_at is not None:
            if worker.last_heartbeat_at < hb_cutoff_naive:
                is_stale = True
        elif worker.created_at is not None and worker.created_at < registration_cutoff_naive:
            # Worker 注册超过 timeout 但从未发送心跳
            is_stale = True

        if not is_stale:
            continue

        # 将 Worker 转为 ERROR
        prev_runtime = worker.runtime_status
        event_type, payload = worker_apply_transition(
            worker, WorkerRuntimeStatus.ERROR,
            actor_type=ActorType.SYSTEM, actor_id="failure_detector",
            context={
                "reason": "heartbeat_timeout",
                "threshold_s": timeout,
                "provider": worker.provider,
            },
        )
        await event_store.record(
            db, event_type=event_type, team_id=worker.team_id,
            actor_type=ActorType.SYSTEM, actor_id="failure_detector",
            target_type="worker", target_id=worker.id, payload=payload,
        )
        failed_worker_ids.append(worker.id)

        # 释放该 Worker 拥有的所有 IN_PROGRESS 任务
        released = await _release_worker_tasks(db, worker, reason="heartbeat_timeout")
        released_task_ids.extend(released)

    return {
        "detector": "heartbeat",
        "failed_workers": len(failed_worker_ids),
        "failed_worker_ids": failed_worker_ids,
        "released_tasks": len(released_task_ids),
        "released_task_ids": released_task_ids,
    }


async def detect_progress_failures(db: AsyncSession) -> dict:
    """扫描进度停滞的 Worker 并将其转为 ERROR 状态。

    Worker 被视为"软故障"当：
      - status == "active"
      - runtime_status == "busy"（有活跃工作）
      - last_progress_at 距今超过 T_PROG 秒
      - last_heartbeat_at 是近期的（Worker 存活，只是卡住了）

    仅检查近期有心跳的 Worker — 无心跳 = 硬故障。

    ⚠️ manual-only by design — last_progress_at 是 task 启动/切换时间非真实进度，
    自动接线会误伤 >T_PROG 的合法长任务（PFL-262）。见模块 docstring「接线状态」。
    """
    now = datetime.now(timezone.utc)
    prog_cutoff = now - timedelta(seconds=T_PROG)
    recent_hb_cutoff = now - timedelta(seconds=T_HB)

    # SQLite 存储无时区信息的 datetime；归一化以便比较
    prog_cutoff_naive = prog_cutoff.replace(tzinfo=None)
    recent_hb_cutoff_naive = recent_hb_cutoff.replace(tzinfo=None)

    stmt = select(Worker).where(
        Worker.status == WorkerStatus.ACTIVE,
        Worker.runtime_status == WorkerRuntimeStatus.BUSY,
    )
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    failed_worker_ids: list[str] = []
    released_task_ids: list[str] = []

    for worker in candidates:
        # 仅检查近期有心跳的 Worker（存活但卡住）
        if worker.last_heartbeat_at is None or worker.last_heartbeat_at < recent_hb_cutoff_naive:
            continue  # 硬故障检测器处理这些

        if worker.last_progress_at is None:
            # 从未产生进度 — 检查 claimed_at 是否可作为代理
            continue

        if worker.last_progress_at >= prog_cutoff_naive:
            continue  # 进度足够近期

        # 将 Worker 转为 ERROR
        event_type, payload = worker_apply_transition(
            worker, WorkerRuntimeStatus.ERROR,
            actor_type=ActorType.SYSTEM, actor_id="failure_detector",
            context={"reason": "progress_timeout", "threshold_s": T_PROG},
        )
        await event_store.record(
            db, event_type=event_type, team_id=worker.team_id,
            actor_type=ActorType.SYSTEM, actor_id="failure_detector",
            target_type="worker", target_id=worker.id, payload=payload,
        )
        failed_worker_ids.append(worker.id)

        # 释放该 Worker 拥有的所有 IN_PROGRESS 任务
        released = await _release_worker_tasks(db, worker, reason="progress_timeout")
        released_task_ids.extend(released)

    return {
        "detector": "progress",
        "failed_workers": len(failed_worker_ids),
        "failed_worker_ids": failed_worker_ids,
        "released_tasks": len(released_task_ids),
        "released_task_ids": released_task_ids,
    }


async def detect_lease_expirations(db: AsyncSession) -> dict:
    """委托给现有租约检测器 (P8-B3)。"""
    from src.services.lease_detector import release_expired_leases

    result = await release_expired_leases(db)
    return {
        "detector": "lease",
        "released_tasks": result["released_count"],
        "released_task_ids": result["released_task_ids"],
    }


async def detect_review_timeouts(db: AsyncSession) -> dict:
    """扫描在 IN_VERIFICATION 状态停留超过 T_REVIEW 的任务。

    不自动拒绝 — 仅发送通知事件。
    Creator/supervisor 必须手动解决过期审核。
    """
    from src.models.event import Event
    from src.models.project import Project

    now = datetime.now(timezone.utc)
    review_cutoff = now - timedelta(seconds=T_REVIEW)
    review_cutoff_naive = review_cutoff.replace(tzinfo=None)

    # 查找所有 IN_VERIFICATION 状态的任务
    stmt = select(Task).where(Task.status == TaskStatus.IN_VERIFICATION)
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    # 批量加载项目 team_id 用于事件作用域
    project_ids = list({t.project_id for t in tasks})
    team_id_map: dict[str, str] = {}
    if project_ids:
        proj_stmt = select(Project.id, Project.team_id).where(
            Project.id.in_(project_ids),
        )
        proj_result = await db.execute(proj_stmt)
        team_id_map = {row[0]: row[1] for row in proj_result.fetchall()}

    overdue_ids: list[str] = []

    for task in tasks:
        # 查找此任务最近的 task.submitted 事件
        event_stmt = (
            select(Event)
            .where(
                Event.target_id == task.id,
                Event.target_type == "task",
                Event.event_type == "task.submitted",
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        event_result = await db.execute(event_stmt)
        submitted_event = event_result.scalar_one_or_none()

        if submitted_event is None:
            continue  # 未找到提交事件 — 无法确定存续时间

        # 使用无时区比较（SQLite 中 DB 存储无时区的 UTC）
        if submitted_event.created_at < review_cutoff_naive:
            overdue_ids.append(task.id)

            team_id_from_task = team_id_map.get(task.project_id)
            if not team_id_from_task:
                logger.warning(
                    "review_timeout: task %s project %s has no team_id — skipping event",
                    task.id, task.project_id,
                )
                continue

            submitted_at_naive = submitted_event.created_at
            submitted_at_iso = submitted_at_naive.isoformat()
            overdue_seconds = (now.replace(tzinfo=None) - submitted_at_naive).total_seconds()

            # 发送 review_timeout 通知事件（WS 广播）
            await event_store.record(
                db,
                event_type="task.review_timeout",
                team_id=team_id_from_task,
                actor_type=ActorType.SYSTEM,
                actor_id="failure_detector",
                target_type="task",
                target_id=task.id,
                payload={
                    "task_id": task.id,
                    "submitted_at": submitted_at_iso,
                    "overdue_seconds": overdue_seconds,
                    "threshold_s": T_REVIEW,
                },
            )
            # P8-B9：同时发送 review.overdue 作为 Creator 通知的 WS 信号
            await event_store.record(
                db,
                event_type="review.overdue",
                team_id=team_id_from_task,
                actor_type=ActorType.SYSTEM,
                actor_id="failure_detector",
                target_type="task",
                target_id=task.id,
                payload={
                    "task_id": task.id,
                    "task_title": task.title,
                    "in_verification_since": submitted_at_iso,
                    "overdue_seconds": int(overdue_seconds),
                    "threshold_s": T_REVIEW,
                },
            )

    return {
        "detector": "review",
        "overdue_tasks": len(overdue_ids),
        "overdue_task_ids": overdue_ids,
    }


async def run_all_detections(
    db: AsyncSession,
    standard_timeout: int | None = None,
    codex_timeout: int | None = None,
) -> dict:
    """运行全部四条检测线并返回摘要。

    P12-B45 (PFL-144): provider-aware heartbeat timeout 参数传递到各检测线。
    P13-B9: 参数改为可选 — 不传时使用 provider_config_service 查询。

    调用方必须在此返回后提交事务。

    ⚠️ 仅 admin 手动端点调用（by design · P100-B158）。
    """
    hb_result = await detect_heartbeat_failures(
        db, standard_timeout=standard_timeout, codex_timeout=codex_timeout,
    )
    prog_result = await detect_progress_failures(db)
    lease_result = await detect_lease_expirations(db)
    review_result = await detect_review_timeouts(db)

    total_failures = (
        hb_result["failed_workers"]
        + prog_result["failed_workers"]
        + lease_result["released_tasks"]
    )

    return {
        "lines": {
            "heartbeat": hb_result,
            "progress": prog_result,
            "lease": lease_result,
            "review": review_result,
        },
        "summary": {
            "total_failures_detected": total_failures,
            "overdue_reviews": review_result["overdue_tasks"],
        },
    }


# ── 阻塞报告 ────────────────────────────────────────────────────

async def report_blocker(
    db: AsyncSession,
    task_id: str,
    *,
    blocker_type: str,
    description: str,
    suggested_fix: str | None,
    expected_version: int,
    worker_id: str,
    worker_team_id: str,
) -> Task:
    """Worker 提交阻塞报告 — 任务释放回 READY。

    按 D-P7-017：阻塞报告不惩罚 Worker。
    - 任务转换 IN_PROGRESS → READY（回到池中）
    - redo_count 不递增
    - Worker 的 runtime_status 不变为 ERROR
    - 事件类型为 ``task.blocker_reported``（而非 ``task.lease_expired``）
    """
    from src.services.task_service import _check_version, _bump_version

    task = await db.get(Task, task_id)
    if task is None:
        raise NotFoundError("task", task_id)

    _check_version(task, expected_version)

    # 仅任务 Owner（worker）可报告阻塞
    if task.owner_type != OwnerType.WORKER or task.owner_id != worker_id:
        raise ForbiddenError(
            "NOT_TASK_OWNER",
            f"Only the task owner can report a blocker on task {task_id}",
            {"ownerType": task.owner_type, "ownerId": task.owner_id},
        )

    # 任务必须是 IN_PROGRESS（Worker 正在处理）
    if task.status != TaskStatus.IN_PROGRESS:
        raise ConflictError(
            "TASK_NOT_IN_PROGRESS",
            f"Task {task_id} is not in_progress (status: {task.status})",
            {"taskId": task_id, "currentStatus": task.status},
        )

    # 构建事件上下文
    context = {
        "reason": "blocker_reported",
        "blocker_type": blocker_type,
        "description": description,
        "suggested_fix": suggested_fix,
    }

    previous_owner_id = task.owner_id

    # P8-B8 收敛：通过 apply_transition + override_event_type 替代直写 status
    # IN_PROGRESS → READY 在事件映射表中的默认类型为 task.lease_expired，
    # 阻塞报告的物理路径相同但语义不同 → override_event_type
    from src.task_state_machine import apply_transition

    event_type, sm_payload = apply_transition(
        task, TaskStatus.READY,
        actor_type=ActorType.WORKER,
        actor_id=worker_id,
        context=context,
        override_event_type="task.blocker_reported",
    )
    task.owner_type = None
    task.owner_id = None
    task.claimed_at = None
    task.lease_expires_at = None
    # 注意：redo_count 不递增 (D-P7-017)
    _bump_version(task)

    # 基于 SM 负载构建事件（阻塞上下文已通过 context 合并进 sm_payload）
    payload = {
        **sm_payload,
        "previous_owner_id": previous_owner_id,
    }

    await event_store.record(
        db,
        event_type="task.blocker_reported",
        team_id=worker_team_id,
        actor_type=ActorType.WORKER,
        actor_id=worker_id,
        target_type="task",
        target_id=task.id,
        payload=payload,
    )

    # 清除 Worker 的活跃任务
    from src.services.worker_scheduler import finish_current_task

    await finish_current_task(db, worker_id)

    return task


# ── 内部辅助函数 ───────────────────────────────────────────────────

async def _release_worker_tasks(
    db: AsyncSession, worker: Worker, *, reason: str
) -> list[str]:
    """释放故障 Worker 拥有的所有 IN_PROGRESS 任务。

    对每个任务：
      - failure_count < N_RETRY：释放到 READY（自动重试）
      - failure_count >= N_RETRY：设置 failure_reason，不释放（已升级）

    返回释放的任务 ID 列表。
    """
    stmt = select(Task).where(
        Task.owner_type == OwnerType.WORKER,
        Task.owner_id == worker.id,
        Task.status == TaskStatus.IN_PROGRESS,
    )
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    released_ids: list[str] = []

    for task in tasks:
        task.failure_count += 1

        if task.failure_count >= N_RETRY:
            # 升级：不释放，标记故障并通知
            task.failure_reason = f"{reason}: auto-retry limit reached (failure_count={task.failure_count})"
            # 发送升级通知事件
            await event_store.record(
                db,
                event_type="task.escalated",
                team_id=worker.team_id,
                actor_type=ActorType.SYSTEM,
                actor_id="failure_detector",
                target_type="task",
                target_id=task.id,
                payload={
                    "task_id": task.id,
                    "failure_count": task.failure_count,
                    "failure_reason": task.failure_reason,
                    "reason": reason,
                    "previous_owner_id": worker.id,
                },
            )
            continue

        # 通过状态机释放任务回 READY (P8-B8)
        previous_owner_id = task.owner_id

        event_type, payload = task_apply_transition(
            task, TaskStatus.READY,
            actor_type=ActorType.SYSTEM, actor_id="failure_detector",
            context={
                "reason": reason,
                "failure_count": task.failure_count,
                "previous_owner_id": previous_owner_id,
            },
        )

        # 清除所有权追踪
        task.owner_type = None
        task.owner_id = None
        task.claimed_at = None
        task.lease_expires_at = None

        # 记录事件
        await event_store.record(
            db,
            event_type=event_type,
            team_id=worker.team_id,
            actor_type=ActorType.SYSTEM,
            actor_id="failure_detector",
            target_type="task",
            target_id=task.id,
            payload=payload,
        )
        released_ids.append(task.id)

    # 清除 Worker 的活跃任务
    from src.services.worker_scheduler import finish_current_task

    await finish_current_task(db, worker.id)

    return released_ids
