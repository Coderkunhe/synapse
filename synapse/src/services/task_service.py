"""Task 服务 — CRUD + 状态机转换 + 事件记录。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, OwnerType, TaskStatus, VerificationStatus, WorkerStatus
from src.exceptions import (
    ConflictError,
    ForbiddenError,
    InvalidStateTransition,
    NotFoundError,
)
from src.models.project import Project
from src.models.task import Task
from src.models.verification import Verification
from src.services.event_store import event_store
from src.task_state_machine import apply_transition, validate_transition
from src.utils.id_gen import derive_id, generate_id
from src.utils.json_utils import safe_dumps, safe_loads

# ── P8-B3: 租约常量 (D-P7-019) ─────────────────────────────
LEASE_DURATION_SECONDS = 600  # T_lease = 10 分钟 — 任务必须在此窗口内启动

# ── 乐观锁 ──────────────────────────────────────────────

def _check_version(task: Task, expected_version: int) -> None:
    """若任务版本不匹配则抛出 ConflictError — 乐观锁。

    每个修改任务状态的变更端点必须在修改任何 Task 字段前调用此函数。
    调用方传入其读取到的版本号（来自之前的 GET 或请求体）。
    若在此期间有其他写入方提交，版本号将不匹配，写入被拒绝。
    """
    if task.version_no != expected_version:
        raise ConflictError(
            "VERSION_CONFLICT",
            f"Task {task.id} was modified by another operation. "
            f"Expected version {expected_version}, current version {task.version_no}. "
            f"Re-read the task and retry.",
            {"expectedVersion": expected_version, "currentVersion": task.version_no},
        )

def _bump_version(task: Task) -> None:
    """变更成功后递增任务版本号。"""
    task.version_no += 1

# ── 状态机 ─────────────────────────────────────────────────

def _validate_transition(task: Task, new_status: str) -> None:
    allowed = Task.ALLOWED_TRANSITIONS.get(task.status, frozenset())
    if new_status not in allowed:
        raise InvalidStateTransition("task", task.id, task.status, new_status)

# ── Task CRUD ─────────────────────────────────────────────────────

async def create_task(
    db: AsyncSession,
    *,
    project_id: str,
    title: str,
    description: str,
    priority: str,
    parent_task_id: str | None,
    batch_id: str | None,
    estimated_effort: str | None,
    tags: list[str] | None,
    metadata: dict | None,
    deadline_at: datetime | None,
    verifications: list[dict],
    actor_type: str,
    actor_id: str,
    team_id: str,
    depends_on: list[dict] | None = None,
) -> Task:
    """创建 Task 并原子性地创建其 Verification 条件。"""

    # 校验项目存在
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)

    # P9-B69: verifications 改为创建时可选项（移除 D-003 创建时强制校验）
    # 若指定了父任务则校验
    if parent_task_id:
        parent = await db.get(Task, parent_task_id)
        if parent is None:
            raise NotFoundError("parent_task", parent_task_id)
        if parent.project_id != project_id:
            raise ConflictError(
                "PARENT_TASK_PROJECT_MISMATCH",
                "Parent task must belong to the same project",
                {"parentTaskId": parent_task_id, "projectId": project_id},
            )

    # 若指定了批次则校验
    if batch_id:
        from src.models.batch import Batch
        batch = await db.get(Batch, batch_id)
        if batch is None:
            raise NotFoundError("batch", batch_id)
        if batch.project_id != project_id:
            raise ConflictError(
                "BATCH_PROJECT_MISMATCH",
                "Batch must belong to the same project",
            )

    # ── P9-B7: depends_on 三段校验 ──────────────────────────
    if depends_on:
        from src.services.task_validation import validate_depends_on
        await validate_depends_on(db, depends_on, project_id)

    task = Task(
        id=generate_id("task"),
        project_id=project_id,
        title=title,
        description=description,
        status=TaskStatus.BACKLOG,
        priority=priority,
        parent_task_id=parent_task_id,
        batch_id=batch_id,
        estimated_effort=estimated_effort,
        tags=safe_dumps(tags),
        metadata_=safe_dumps(metadata),
        depends_on=safe_dumps(depends_on),
        deadline_at=deadline_at,
        create_user_id=actor_id,
    )
    db.add(task)

    # 创建验证记录
    verification_objs = []
    for v in verifications:
        ver = Verification(
            id=generate_id("verification"),
            task_id=task.id,
            type=v["type"],
            description=v["description"],
            criteria=safe_dumps(v.get("criteria")),
            status=VerificationStatus.PENDING,
            create_user_id=actor_id,
        )
        db.add(ver)
        verification_objs.append(ver)

    # 记录事件
    await event_store.record(
        db,
        event_type="task.created",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="task",
        target_id=task.id,
        payload={
            "title": title,
            "priority": priority,
            "verification_count": len(verifications),
            "status": TaskStatus.BACKLOG,
        },
    )

    # Flush 以便调用方可读取服务端默认值（version_no 等）
    await db.flush()

    return task

async def get_task(db: AsyncSession, task_id: str) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise NotFoundError("task", task_id)
    return task


async def update_task(
    db: AsyncSession,
    task_id: str,
    *,
    title: str | None,
    description: str | None,
    priority: str | None,
    estimated_effort: str | None,
    tags: list[str] | None,
    metadata: dict | None,
    deadline_at: datetime | None,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    task = await get_task(db, task_id)
    _check_version(task, expected_version)

    changed = False
    if title is not None:
        task.title = title
        changed = True
    if description is not None:
        task.description = description
        changed = True
    if priority is not None:
        task.priority = priority
        changed = True
    if estimated_effort is not None:
        task.estimated_effort = estimated_effort
        changed = True
    if tags is not None:
        task.tags = safe_dumps(tags)
        changed = True
    if metadata is not None:
        task.metadata_ = safe_dumps(metadata)
        changed = True
    if deadline_at is not None:
        task.deadline_at = deadline_at
        changed = True

    if changed:
        _bump_version(task)
        await event_store.record(
            db,
            event_type="task.updated",
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="task",
            target_id=task.id,
            payload={"updated_fields": [k for k, v in locals().items() if v is not None and k not in ("db", "task_id", "actor_type", "actor_id", "team_id", "task", "changed", "expected_version")]},
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

    # 校验状态转换：必须处于 backlog 或 ready
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

    return task


# ── P8-B3/P8-B4: 重导出批量协作函数 ──────────────
# 这些函数位于 cooperation.py（在 B4 中提取以保持 task_service ≤800 行）。
from src.services.cooperation import assign_batch, claim_batch  # noqa: E402, F401
import src.services.cooperation as _coop  # noqa: E402

# 注入私有辅助函数，使 cooperation.py 可使用 _check_version / _bump_version
_coop._inject_deps(_check_version, _bump_version)

# ── P8-B1/B4: 提交 ──────────────────────────────────────────────

async def submit_task(
    db: AsyncSession,
    task_id: str,
    *,
    summary: str,
    evidence: dict | None,
    verification_results: list[dict],
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """提交任务进行验证。提交者必须是任务 owner。

    P8-B4: 使用状态机的 ``apply_transition``，与其他 B1 转换保持一致。
    当提交者是 Worker 时，清除 Worker 的 active_task_id 并将运行时状态转为 IDLE。
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    ok = task.owner_type == actor_type and task.owner_id == actor_id  # P10-B7
    if not ok and task.owner_type == OwnerType.MEMBER and actor_type == ActorType.HUMAN:
        ok = derive_id(task.owner_id, "worker") == actor_id
    if not ok:
        raise ForbiddenError(
            "NOT_TASK_OWNER",
            f"Only the task owner ({task.owner_type}:{task.owner_id}) can submit",
            {"ownerType": task.owner_type, "ownerId": task.owner_id},
        )

    # 处理 owner 提交的验证结果
    for vr in verification_results:
        ver = await db.get(Verification, vr["verification_id"])
        if ver is None:
            raise NotFoundError("verification", vr["verification_id"])
        if ver.task_id != task_id:
            raise ConflictError(
                "VERIFICATION_TASK_MISMATCH",
                f"Verification {vr['verification_id']} does not belong to task {task_id}",
            )
        # 重做时重置验证：清除之前的裁决以便验证者重新评估
        # P8-B8: 当之前已执行的验证在任务重新提交时被重置，写入 verification.reset 事件。
        if ver.status != VerificationStatus.PENDING:
            previous_ver_status = ver.status
            ver.status = VerificationStatus.PENDING
            ver.verified_by = None
            ver.verified_at = None
            ver.rejection_reason = None
            await event_store.record(
                db,
                event_type="verification.reset",
                team_id=team_id,
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="verification",
                target_id=ver.id,
                payload={
                    "task_id": task_id,
                    "previous_status": previous_ver_status,
                    "new_status": VerificationStatus.PENDING,
                    "reason": "task_resubmitted",
                },
            )
        # Owner 可提交自评证据，但最终状态由验证者设定
        if vr.get("evidence"):
            evidence_val = vr["evidence"]
            if isinstance(evidence_val, str):
                ver.evidence = safe_dumps({"submitter_note": evidence_val})
            else:
                ver.evidence = safe_dumps(evidence_val)

    # 使用状态机进行转换 (P8-B4: 与 B1 模式一致)
    event_type, payload = apply_transition(
        task, TaskStatus.IN_VERIFICATION,
        actor_type=actor_type, actor_id=actor_id,
        context={
            "summary": summary,
            "verification_results_count": len(verification_results),
        },
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

    # P8-B4: 提交后清除 Worker 的活跃任务
    if actor_type == ActorType.WORKER:
        from src.services.worker_scheduler import finish_current_task
        await finish_current_task(db, actor_id)

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

    return task

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

    if not task.description:
        raise ConflictError(
            "TASK_NOT_READY",
            "Task description is required before moving to READY",
        )
    ver_count = await _count_verifications(db, task_id)
    if ver_count < 1:
        # P9-B69: 若任务无验证条件，自动创建默认 "Manual PM review"
        default_ver = Verification(
            id=generate_id("verification"),
            task_id=task.id,
            type="manual",
            description="Manual PM review",
            criteria=None,
            status=VerificationStatus.PENDING,
            create_user_id=actor_id,
        )
        db.add(default_ver)

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

    return task


async def pause_task(
    db: AsyncSession,
    task_id: str,
    *,
    reason: str,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """暂停进行中的任务。仅任务 owner 或管理员可暂停。

    PAUSED 是独立状态 (D-P7-020)：
    - 暂停的任务不消耗租约
    - 暂停的任务不阻塞 Worker 队列
    - Worker 应在下次心跳时停止计算
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)

    event_type, payload = apply_transition(
        task, TaskStatus.PAUSED,
        actor_type=actor_type,
        actor_id=actor_id,
        context={"reason": reason},
    )
    task.paused_at = datetime.now(timezone.utc)
    task.paused_by = actor_id
    task.pause_reason = reason
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

    return task


async def resume_task(
    db: AsyncSession,
    task_id: str,
    *,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """将暂停的任务恢复为 IN_PROGRESS。"""
    task = await get_task(db, task_id)
    _check_version(task, expected_version)

    event_type, payload = apply_transition(
        task, TaskStatus.IN_PROGRESS,
        actor_type=actor_type,
        actor_id=actor_id,
        context={"resumed_from": TaskStatus.PAUSED},
    )
    task.paused_at = None
    task.paused_by = None
    task.pause_reason = None
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

    return task


async def terminate_task(
    db: AsyncSession,
    task_id: str,
    *,
    reason: str,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """永久终止任务 → CANCELLED（终态）。

    与 pause/resume 不同，CANCELLED 是永久的 — 任务永远不会完成。
    可从以下状态转入：READY、IN_PROGRESS、PAUSED（任意终态前状态）。

    若任务有活跃 Worker，Worker 的 active_task_id 将在下次心跳时释放
    （心跳检测到 status != IN_PROGRESS）。
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)

    previous_owner_id = task.owner_id

    event_type, payload = apply_transition(
        task, TaskStatus.CANCELLED,
        actor_type=actor_type,
        actor_id=actor_id,
        context={"reason": reason, "previous_owner_id": previous_owner_id},
    )
    # 释放所有权，使任务不可被重新认领
    task.owner_type = None
    task.owner_id = None
    task.paused_at = None
    task.paused_by = None
    task.pause_reason = None
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

    return task


async def _count_verifications(db: AsyncSession, task_id: str) -> int:
    """返回任务的验证记录数量。"""
    from sqlalchemy import func as sa_func, select as sa_select
    result = await db.execute(
        sa_select(sa_func.count(Verification.id)).where(Verification.task_id == task_id)
    )
    return result.scalar() or 0


# ── 查询 ─────────────────────────────────────────────────────────


async def task_to_response(task: Task, db: AsyncSession) -> dict:
    """将 Task ORM 对象转换为响应字典，含 JSON 反序列化和 owner 名称解析。"""
    # ── P11-B14: 解析 owner 名称 ──────────────────────────
    owner_name = None
    if task.owner_type and task.owner_id:
        if task.owner_type == OwnerType.WORKER:
            from src.models.worker import Worker
            result = await db.execute(
                select(Worker.name).where(Worker.id == task.owner_id)
            )
            owner_name = result.scalar()
        elif task.owner_type == OwnerType.MEMBER:
            from src.models.member import Member
            result = await db.execute(
                select(Member.display_name).where(Member.id == task.owner_id)
            )
            owner_name = result.scalar()

    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "owner_type": task.owner_type,
        "owner_id": task.owner_id,
        "owner_name": owner_name,
        "status": task.status,
        "priority": task.priority,
        "parent_task_id": task.parent_task_id,
        "batch_id": task.batch_id,
        "estimated_effort": task.estimated_effort,
        "tags": safe_loads(task.tags),
        "metadata": safe_loads(task.metadata_),
        "version_no": task.version_no,
        "deadline_at": task.deadline_at,
        "is_disabled": task.is_disabled,
        "create_user_id": task.create_user_id,
        "last_update_user_id": task.last_update_user_id,
        "remark": task.remark,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
        "paused_at": task.paused_at.isoformat() if task.paused_at else None,
        "paused_by": task.paused_by,
        "pause_reason": task.pause_reason,
        "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
        "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
        "redo_count": task.redo_count,
        "failure_count": task.failure_count,
        "failure_reason": task.failure_reason,
        "depends_on": safe_loads(task.depends_on),
    }
