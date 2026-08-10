"""Cooperation 批量操作 — claim_batch + assign_batch (P8-B3)。

从 ``task_service.py`` 中抽取（P8-B4），以保持文件大小在 800 行
pre-commit 门禁以内。由 ``task_service.py`` 重新导出以保持向后兼容 —
外部调用方仍应从 ``task_service`` 导入。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, OwnerType, TaskStatus, WorkerStatus
from src.exceptions import ConflictError, NotFoundError
from src.models.task import Task
from src.services.event_store import event_store
from src.task_state_machine import apply_transition
from src.utils.json_utils import safe_loads


# 从 task_service 重新导入以避免循环导入
_check_version = None  # 由 task_service 在导入后设置
_bump_version = None   # 由 task_service 在导入后设置
LEASE_DURATION_SECONDS = 600  # T_lease = 10 分钟


def _inject_deps(check_version, bump_version):
    """由 task_service 在导入后调用，注入其私有辅助函数。"""
    global _check_version, _bump_version
    _check_version = check_version
    _bump_version = bump_version


async def claim_batch(
    db: AsyncSession,
    batch_id: str,
    *,
    worker_id: str,
    worker_team_id: str,
    actor_type: str = ActorType.WORKER,
) -> dict:
    """原子性认领 Batch 中所有 READY 任务（拉取模式）。Worker 和 Member 均可认领。

    按 D5：Batch 是原子分配单元，但租约在 Task 级别追踪。
    Batch 中所有 READY 任务一起认领；如果任一任务版本检查失败，
    整个 Batch 认领被拒绝（调用方应重新读取并重试）。

    返回：
        {"claimed_count": N, "task_ids": [...]}
    """
    from src.models.batch import Batch

    batch = await db.get(Batch, batch_id)
    if batch is None:
        raise NotFoundError("batch", batch_id)

    # 验证 Worker 存在且处于活跃状态（仅 Worker 认领时需要）
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

    # 查找此 Batch 中所有 READY 状态的任务
    stmt = (
        select(Task)
        .where(
            Task.batch_id == batch_id,
            Task.status == TaskStatus.READY,
        )
        .order_by(Task.id)
    )
    result = await db.execute(stmt)
    ready_tasks = result.scalars().all()

    if not ready_tasks:
        raise ConflictError(
            "NO_READY_TASKS_IN_BATCH",
            f"Batch {batch_id} has no tasks in READY status",
        )

    # P14-B10 PFL-171: claim 路径 capability 校验（与 assign 路径对齐）
    if actor_type == ActorType.WORKER:
        for task in ready_tasks:
            req_caps = safe_loads(task.required_capabilities)
            if not req_caps:
                continue
            cap_tags = worker.capability_tags or {}
            cap_names: list[str] = cap_tags.get("names", [])
            if not cap_names:
                raise ConflictError(
                    "WORKER_NO_CAPABILITIES",
                    f"Worker '{worker.name}' has no declared capabilities. "
                    f"Task '{task.id}' requires: {', '.join(req_caps)}. "
                    f"Worker must complete handshake with capability declarations.",
                    {"workerId": worker_id, "requiredCapabilities": req_caps},
                )
            missing = [c for c in req_caps if c not in cap_names]
            if missing:
                raise ConflictError(
                    "WORKER_MISSING_CAPABILITIES",
                    f"Worker '{worker.name}' lacks required capabilities: {', '.join(missing)}. "
                    f"Worker declared: {', '.join(cap_names)}. "
                    f"Task '{task.id}' requires: {', '.join(req_caps)}.",
                    {"workerId": worker_id, "taskId": task.id, "missingCapabilities": missing,
                     "workerCapabilities": cap_names, "requiredCapabilities": req_caps},
                )

    now = datetime.now(timezone.utc)
    claimed_ids: list[str] = []

    for task in ready_tasks:
        # P11-B60 G3: 依赖就绪检查（与 claim_task 对齐）
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
                            f"Task {task.id} depends on {dep['task_id']} "
                            f"(status: {dep_task.status}, need: completed)",
                        )

        # 检查无冲突认领
        if task.owner_id is not None and task.owner_id != worker_id:
            raise ConflictError(
                "TASK_ALREADY_CLAIMED",
                f"Task {task.id} in batch {batch_id} is already claimed "
                f"by {task.owner_type}:{task.owner_id}",
            )

        previous_status = task.status
        task.owner_type = actor_type
        task.owner_id = worker_id
        task.claimed_at = now
        task.lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

        # P8-B8：使用状态机进行转换 + 事件（替代直接赋值）
        event_type, payload = apply_transition(
            task, TaskStatus.IN_PROGRESS,
            actor_type=actor_type, actor_id=worker_id,
            context={
                "previous_status": previous_status,
                "batch_id": batch_id,
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
        claimed_ids.append(task.id)

    return {"claimed_count": len(claimed_ids), "task_ids": claimed_ids}


async def assign_batch(
    db: AsyncSession,
    *,
    task_ids: list[str],
    owner_type: str,
    owner_id: str,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> dict:
    """批量分配多个任务给一个 Owner（推送模式，D-P7-023）。

    全有或全无：如果任一任务验证失败，整个批次被拒绝。
    """
    if not task_ids:
        raise ConflictError(
            "EMPTY_TASK_LIST",
            "At least one task ID must be provided for batch assignment",
        )
    if len(task_ids) > 20:
        raise ConflictError(
            "BATCH_TOO_LARGE",
            f"Batch assign limited to 20 tasks, got {len(task_ids)}",
        )

    # 验证 Owner
    if owner_type == OwnerType.WORKER:
        from src.models.worker import Worker

        owner = await db.get(Worker, owner_id)
        if owner is None or owner.team_id != team_id:
            raise NotFoundError("worker", owner_id)
        if owner.status != WorkerStatus.ACTIVE:
            raise ConflictError(
                "WORKER_NOT_ACTIVE",
                f"Worker {owner_id} is not active. "
                f"Activate the worker via POST /v1/workers/{owner_id}/handshake",
            )
    else:
        from src.models.member import Member

        owner = await db.get(Member, owner_id)
        if owner is None or owner.team_id != team_id:
            raise NotFoundError("member", owner_id)

    now = datetime.now(timezone.utc)
    assigned_ids: list[str] = []
    errors: list[dict] = []

    for task_id in task_ids:
        try:
            from src.services.task_service import get_task as _get_task

            task = await _get_task(db, task_id)
        except NotFoundError:
            errors.append({"task_id": task_id, "error": "NOT_FOUND"})
            continue

        # 验证状态转换
        try:
            from src.services.task_service import (  # noqa: F811
                _validate_transition as _vt,
            )

            _vt(task, TaskStatus.IN_PROGRESS)
        except Exception:
            from src.exceptions import InvalidStateTransition

            errors.append(
                {
                    "task_id": task_id,
                    "error": "INVALID_TRANSITION",
                    "current_status": task.status,
                }
            )
            continue

        if task.owner_id is not None and task.owner_id != owner_id:
            errors.append(
                {
                    "task_id": task_id,
                    "error": "ALREADY_CLAIMED",
                    "current_owner": f"{task.owner_type}:{task.owner_id}",
                }
            )
            continue

        previous_status = task.status
        task.owner_type = owner_type
        task.owner_id = owner_id
        if owner_type == OwnerType.WORKER:
            task.claimed_at = now
            task.lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

        # P8-B8：使用状态机进行转换 + 事件（替代直接赋值）
        context: dict = {
            "owner_type": owner_type,
            "owner_id": owner_id,
            "previous_status": previous_status,
            "batch_assign": True,
        }
        if owner_type == OwnerType.WORKER:
            context["claimed_at"] = now.isoformat()
            context["lease_expires_at"] = task.lease_expires_at.isoformat()

        event_type, payload = apply_transition(
            task, TaskStatus.IN_PROGRESS,
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
        assigned_ids.append(task_id)

    if errors:
        raise ConflictError(
            "BATCH_ASSIGN_PARTIAL_FAILURE",
            f"{len(assigned_ids)} assigned, {len(errors)} failed",
            {"assigned": assigned_ids, "errors": errors},
        )

    return {"assigned_count": len(assigned_ids), "task_ids": assigned_ids}
