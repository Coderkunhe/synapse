"""Task 激活服务 — ready/assign/claim/cancel 状态转换 · 涵盖 backlog→ready→in_progress 激活管线 + cancel 终态 · 调用方持有事务不提交。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, OwnerType, TaskStatus, WorkerStatus
from src.exceptions import (
    ConflictError,
    NotFoundError,
)
from src.models.task import Task
from src.services.event_store import event_store
from src.services.task_core import (
    _bump_version,
    _check_no_pending_auth,
    _check_version,
    _count_verifications,
    _get_verifications,
    _validate_transition,
    get_task,
)
from src.services.ws_manager import ws_manager
from src.task_state_machine import apply_transition
from src.utils.json_utils import safe_loads

# ── P8-B3: 租约常量 (D-P7-019) ─────────────────────────────
LEASE_DURATION_SECONDS = 600  # T_lease = 10 分钟 — 任务必须在此窗口内启动


# ── P8-B1: 状态机驱动的转换 ─────────────────────────

async def ready_task(
    db: AsyncSession,
    task_id: str,
    *,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """将任务从 BACKLOG 提升为 READY — 使其可被认领。

    守卫条件（依据 data-model.md）：
    - 任务必须有非空描述
    - 任务必须至少有 1 个验证条件
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)

    if not task.description:
        raise ConflictError(
            "TASK_NOT_READY",
            "Task description is required before moving to READY",
        )
    ver_count = await _count_verifications(db, task_id)
    if ver_count < 1:
        raise ConflictError(
            "TASK_NOT_READY",
            "Task must have at least one verification condition before moving to READY",
        )

    # P11-B70: Verification 可判定性校验 — 拒绝模糊描述
    vague_set = {
        "代码写好了", "功能正常", "没问题", "做好了", "完成了",
        "code is done", "works fine", "looks good", "done",
        "测试通过", "lint过了", "没问题了", "it works",
        "差不多", "还行", "ok", "好了",
    }
    verifications = await _get_verifications(db, task_id)
    for ver in verifications:
        desc = (ver.description or "").strip()
        if len(desc) < 6:
            raise ConflictError(
                "VERIFICATION_NOT_DECIDABLE",
                f"Verification '{desc}' is too short ({len(desc)} chars). "
                f"Must be ≥6 characters with specific, machine-verifiable criteria. "
                f"Example: 'pytest 23/23 passed, ruff 0 errors'",
            )
        if desc.lower() in vague_set:
            raise ConflictError(
                "VERIFICATION_NOT_DECIDABLE",
                f"Verification '{desc}' is too vague. "
                f"Use specific criteria with measurable indicators. "
                f"Example: 'POST /login returns 200 + response contains access_token'",
            )

    event_type, payload = apply_transition(
        task, TaskStatus.READY, actor_type=actor_type, actor_id=actor_id,
    )
    _bump_version(task)

    await event_store.record(
        db,
        event_type=event_type,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="task",
        target_id=task.id,
        payload=payload,
    )

    # P11-B21 PFL-041: WS push — notify creator that task is ready
    if task.create_user_id:
        await ws_manager.broadcast_to_actor(
            task.create_user_id,
            {
                "type": "event",
                "data": {
                    "event_type": event_type,
                    "task_id": task.id,
                    "status": task.status,
                },
            },
        )

    return task


async def assign_task(
    db: AsyncSession,
    task_id: str,
    *,
    owner_type: str,
    owner_id: str,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)

    # P11-B72: 必须处于 ready — 不可从 backlog 直接分配（绕过 decidability gate）
    if task.status != TaskStatus.READY:
        raise ConflictError(
            "TASK_NOT_READY",
            f"Task must be in 'ready' status to be assigned. "
            f"Current status: {task.status}. "
            f"Use POST /v1/tasks/{task_id}/ready first to pass the decidability gate.",
            {"taskId": task.id, "currentStatus": task.status, "requiredStatus": TaskStatus.READY},
        )

    # 校验状态转换
    target_status = TaskStatus.IN_PROGRESS
    _validate_transition(task, target_status)

    # 校验 owner 在团队中存在
    if owner_type == OwnerType.MEMBER:
        from src.models.member import Member
        owner = await db.get(Member, owner_id)
        if owner is None or owner.team_id != team_id:
            raise NotFoundError("member", owner_id)
    elif owner_type == OwnerType.WORKER:
        from src.models.worker import Worker
        owner = await db.get(Worker, owner_id)
        if owner is None or owner.team_id != team_id:
            raise NotFoundError("worker", owner_id)
        if owner.status != WorkerStatus.ACTIVE:
            raise ConflictError(
                "WORKER_NOT_ACTIVE",
                f"Worker {owner_id} is not active (status: {owner.status}). "
                f"Activate the worker via POST /v1/workers/{owner_id}/handshake",
            )
    else:
        raise ConflictError(
            "INVALID_OWNER_TYPE",
            f"owner_type must be 'member' or 'worker', got '{owner_type}'",
        )

    previous_status = task.status
    task.owner_type = owner_type
    task.owner_id = owner_id

    # Worker 分配获取租约 (P8-B3)
    now = datetime.now(timezone.utc)
    if owner_type == OwnerType.WORKER:
        task.claimed_at = now
        task.lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

    # P8-B8: 使用状态机进行转换 + 事件（替代直接赋值）
    context: dict = {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "previous_status": previous_status,
    }
    if owner_type == OwnerType.WORKER:
        context["claimed_at"] = now.isoformat()
        context["lease_expires_at"] = task.lease_expires_at.isoformat()

    event_type, payload = apply_transition(
        task, target_status,
        actor_type=actor_type, actor_id=actor_id,
        context=context,
    )
    _bump_version(task)

    await event_store.record(
        db,
        event_type=event_type,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="task",
        target_id=task.id,
        payload=payload,
    )

    # P11-B21 PFL-041: WS push — notify assignee
    await ws_manager.broadcast_to_actor(
        owner_id,
        {
            "type": "event",
            "data": {
                "event_type": event_type,
                "task_id": task.id,
                "status": task.status,
                "owner_type": owner_type,
                "owner_id": owner_id,
            },
        },
    )

    return task


async def claim_task(
    db: AsyncSession,
    task_id: str,
    *,
    worker_id: str,
    worker_team_id: str,
    expected_version: int,
    actor_type: str = ActorType.WORKER,
) -> Task:
    """认领一个 ready 状态的任务。Worker 和 Member 均可认领。

    使用乐观锁：若任务版本在认领者上次读取后发生变化，
    则认领被拒绝，返回 VERSION_CONFLICT (409)。
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=worker_id)

    # 任务必须未分配或已分配给此认领者（在校验状态转换之前检查，
    # 以便返回清晰的 TASK_ALREADY_CLAIMED 而非 InvalidStateTransition）
    if task.owner_id is not None and task.owner_id != worker_id:
        raise ConflictError(
            "TASK_ALREADY_CLAIMED",
            f"Task {task_id} is already claimed by {task.owner_type}:{task.owner_id}",
        )

    # ── P9-B6: 依赖就绪检查 ────────────────────────────────────
    if task.depends_on:
        deps = safe_loads(task.depends_on)
        if deps:
            for dep in deps:
                dep_task = await db.get(Task, dep["task_id"])
                if dep_task is None:
                    raise NotFoundError("task", dep["task_id"])
                if dep_task.status != TaskStatus.COMPLETED:
                    raise ConflictError(
                        "TASK_DEPENDENCY_NOT_READY",
                        f"Task depends on {dep['task_id']} "
                        f"(status: {dep_task.status}, need: completed)",
                    )

    # P11-B72: 必须处于 ready — 不可从 backlog 直接认领（绕过 decidability gate）
    if task.status != TaskStatus.READY:
        raise ConflictError(
            "TASK_NOT_READY",
            f"Task must be in 'ready' status to be claimed. "
            f"Current status: {task.status}. "
            f"Wait for an orchestrator to run POST /v1/tasks/{task_id}/ready first.",
            {"taskId": task.id, "currentStatus": task.status, "requiredStatus": TaskStatus.READY},
        )

    _validate_transition(task, TaskStatus.IN_PROGRESS)

    # 校验 Worker 存在且活跃（仅 Worker 认领时需要）
    if actor_type == ActorType.WORKER:
        from src.models.worker import Worker
        worker = await db.get(Worker, worker_id)
        if worker is None:
            raise NotFoundError("worker", worker_id)
        if worker.status != WorkerStatus.ACTIVE:
            raise ConflictError(
                "WORKER_NOT_ACTIVE",
                f"Worker {worker_id} is not active (status: {worker.status}). "
                f"Activate the worker via POST /v1/workers/{worker_id}/handshake",
            )

    previous_status = task.status
    now = datetime.now(timezone.utc)
    task.owner_type = actor_type
    task.owner_id = worker_id
    task.claimed_at = now
    task.lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

    # P8-B8: 使用状态机进行转换 + 事件（替代直接赋值）
    event_type, payload = apply_transition(
        task, TaskStatus.IN_PROGRESS,
        actor_type=actor_type, actor_id=worker_id,
        context={
            "previous_status": previous_status,
            "claimed_at": now.isoformat(),
            "lease_expires_at": task.lease_expires_at.isoformat(),
        },
    )
    _bump_version(task)

    await event_store.record(
        db,
        event_type=event_type,
        team_id=worker_team_id,
        actor_type=actor_type,
        actor_id=worker_id,
        target_type="task",
        target_id=task.id,
        payload=payload,
    )

    # P11-B21 PFL-041: WS push — notify claimer
    await ws_manager.broadcast_to_actor(
        worker_id,
        {
            "type": "event",
            "data": {
                "event_type": event_type,
                "task_id": task.id,
                "status": task.status,
                "owner_type": actor_type,
                "owner_id": worker_id,
            },
        },
    )

    return task


async def cancel_task(
    db: AsyncSession,
    task_id: str,
    *,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """取消任务。任意非终态 → cancelled。"""
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)

    _validate_transition(task, TaskStatus.CANCELLED)

    # P8-B8: 使用状态机进行转换 + 事件（替代直接赋值）
    event_type, payload = apply_transition(
        task, TaskStatus.CANCELLED,
        actor_type=actor_type, actor_id=actor_id,
    )
    _bump_version(task)

    await event_store.record(
        db,
        event_type=event_type,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="task",
        target_id=task.id,
        payload=payload,
    )

    # P8-B9: 终态转换后检查批次完成状态
    from src.services.batch_service import check_batch_completion
    await check_batch_completion(db, task, team_id, actor_type, actor_id)

    # P11-B21 PFL-041: WS push — notify owner and creator
    cancel_event = {
        "type": "event",
        "data": {
            "event_type": event_type,
            "task_id": task.id,
            "status": task.status,
        },
    }
    if task.owner_id:
        await ws_manager.broadcast_to_actor(task.owner_id, cancel_event)
    if task.create_user_id and task.create_user_id != task.owner_id:
        await ws_manager.broadcast_to_actor(task.create_user_id, cancel_event)

    return task
