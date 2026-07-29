"""Batch 服务 — CRUD + 批次生命周期 + 事件记录。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import BatchStatus, ProjectStatus, WorkerStatus
from src.exceptions import ConflictError, NotFoundError
from src.models.worker import Worker
from src.models.batch import Batch
from src.models.project import Project
from src.models.task import Task
from src.services.event_store import event_store
from src.task_state_machine import is_terminal
from src.utils.id_gen import generate_id


async def create_batch(
    db: AsyncSession,
    *,
    project_id: str,
    name: str,
    description: str | None,
    order: int | None,
    phase: str | None = None,
    batch_number: int | None = None,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Batch:
    """为项目创建 Batch。验证项目存在且未被归档。

    若项目启用了 Phase 模式（``use_phase_mode=True``），且调用方未显式
    提供 ``phase`` / ``batch_number``，则自动从项目当前 Phase 派生：

    - ``phase`` ← ``project.current_phase``（若调用方未传）
    - ``batch_number`` ← 该项目+Phase 内最大编号 + 1（从 1 开始）

    记录 ``batch.created`` 事件。
    """
    # 验证项目存在
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)

    if project.status == ProjectStatus.ARCHIVED:
        raise ConflictError(
            "PROJECT_ARCHIVED",
            "Cannot create batches in an archived project",
        )

    # ── Phase 模式：自动派生 phase + batch_number ──
    if project.use_phase_mode:
        if phase is None and project.current_phase:
            phase = project.current_phase
        if batch_number is None and phase:
            # 查询该项目+Phase 内最大的 batch_number
            from sqlalchemy import func
            max_num_result = await db.execute(
                select(func.max(Batch.batch_number)).where(
                    Batch.project_id == project_id,
                    Batch.phase == phase,
                )
            )
            max_num = max_num_result.scalar()
            batch_number = (max_num or 0) + 1

    batch = Batch(
        id=generate_id("batch"),
        project_id=project_id,
        name=name,
        description=description,
        order=order,
        phase=phase,
        batch_number=batch_number,
        status=BatchStatus.OPEN,
        create_user_id=actor_id,
    )
    db.add(batch)

    await event_store.record(
        db,
        event_type="batch.created",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="batch",
        target_id=batch.id,
        payload={"name": name, "project_id": project_id, "status": BatchStatus.OPEN},
    )

    return batch


async def get_batch(db: AsyncSession, batch_id: str) -> Batch:
    """按 ID 获取 Batch，未找到则抛出 NotFoundError。"""
    batch = await db.get(Batch, batch_id)
    if batch is None:
        raise NotFoundError("batch", batch_id)
    return batch


async def list_batches(
    db: AsyncSession,
    project_id: str,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Batch], str | None, int]:
    """游标分页列出项目 Batch（按 order ASC、created_at DESC 排序）。"""
    query = (
        select(Batch)
        .where(Batch.project_id == project_id)
        .order_by(Batch.order.asc().nullslast(), Batch.created_at.desc())
    )
    # 计数总数
    count_query = select(Batch).where(Batch.project_id == project_id)
    total_result = await db.execute(count_query)
    total = len(total_result.scalars().all())

    # 按 id 游标分页
    if cursor:
        cursor_stmt = select(Batch.created_at, Batch.id).where(Batch.id == cursor)
        cursor_result = await db.execute(cursor_stmt)
        cursor_row = cursor_result.one_or_none()
        if cursor_row:
            cursor_ts, _ = cursor_row
            query = query.where(
                (Batch.created_at < cursor_ts)
                | ((Batch.created_at == cursor_ts) & (Batch.id < cursor))
            )

    query = query.limit(limit + 1)
    result = await db.execute(query)
    rows = result.scalars().all()

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].id

    return list(rows), next_cursor, total


def batch_to_response(batch: Batch) -> dict:
    """将 Batch ORM 对象转换为响应字典。"""
    return {
        "id": batch.id,
        "project_id": batch.project_id,
        "name": batch.name,
        "description": batch.description,
        "status": batch.status,
        "order": batch.order,
        "is_disabled": batch.is_disabled,
        "create_user_id": batch.create_user_id,
        "last_update_user_id": batch.last_update_user_id,
        "remark": batch.remark,
        "version_no": batch.version_no,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "completed_at": batch.completed_at,
        "phase": batch.phase,  # P9-B6
        "batch_number": batch.batch_number,  # P9-B6
        "assigned_to": batch.assigned_worker_id,  # P9-B57
    }


# ── P8-B9：Batch 批量创建任务 + 完成检测 ──────────────────────────


async def create_tasks_batch(
    db: AsyncSession,
    *,
    project_id: str,
    tasks: list[dict],
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> list[Task]:
    """原子性批量创建多个 Task（P8-B9, D-P7-023）。

    每个任务获得各自的 ``task.created`` 事件和验证记录。
    调用方持有事务 — 任何异常中止所有创建。
    """
    from src.services.task_service import create_task

    created: list[Task] = []
    for task_data in tasks:
        task = await create_task(
            db,
            project_id=project_id,
            title=task_data["title"],
            description=task_data.get("description"),
            priority=task_data.get("priority", "p2"),
            parent_task_id=task_data.get("parent_task_id"),
            batch_id=task_data.get("batch_id"),
            estimated_effort=task_data.get("estimated_effort"),
            tags=task_data.get("tags"),
            required_capabilities=task_data.get("required_capabilities"),
            metadata=task_data.get("metadata"),
            deadline_at=task_data.get("deadline_at"),
            verifications=task_data["verifications"],
            actor_type=actor_type,
            actor_id=actor_id,
            team_id=team_id,
        )
        created.append(task)
    return created


async def check_batch_completion(
    db: AsyncSession,
    task: Task,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> None:
    """如果 Batch 中所有任务均已终止，则触发 batch.completed 事件。

    当任务没有 batch_id 或存在非终止状态的任务时为空操作。

    终止状态：COMPLETED、CANCELLED（按 is_terminal）。
    REJECTED 非终止 — 任务可以重新提交。
    """
    if not task.batch_id:
        return

    tasks_in_batch = await db.execute(
        select(Task).where(Task.batch_id == task.batch_id)
    )
    batch_tasks = tasks_in_batch.scalars().all()

    if batch_tasks and all(is_terminal(t.status) for t in batch_tasks):
        await event_store.record(
            db,
            event_type="batch.completed",
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="batch",
            target_id=task.batch_id,
            payload={
                "batch_id": task.batch_id,
                "completed_task_count": len(batch_tasks),
                "final_task_id": task.id,
            },
        )


# ── P9-B57：Batch 原子性 — 分配端点 ─────────────────────────────


async def assign_batch(
    db: AsyncSession,
    *,
    batch_id: str,
    worker_id: str,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Batch:
    """将 Batch 分配给一个 Worker（分配原子 — P7-007 短期落地）。

    验证规则：
    - Batch 必须存在且状态为 open
    - Worker 必须存在且属于同一 team
    - Worker 必须为 active 状态

    记录 ``batch.assigned`` 事件。
    """
    batch = await db.get(Batch, batch_id)
    if batch is None:
        raise NotFoundError("batch", batch_id)

    if batch.status != BatchStatus.OPEN:
        raise ConflictError(
            "BATCH_NOT_OPEN",
            f"Batch {batch_id} is {batch.status}, only open batches can be assigned",
        )

    worker = await db.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError("worker", worker_id)

    if worker.team_id != team_id:
        raise NotFoundError("worker", worker_id)  # 不暴露其他 team 的 worker

    if worker.status != WorkerStatus.ACTIVE:
        raise ConflictError(
            "WORKER_NOT_ACTIVE",
            f"Worker {worker_id} is {worker.status}, only active agents can be assigned batches. "
            f"Activate the worker via POST /v1/workers/{worker_id}/handshake",
        )

    batch.assigned_worker_id = worker_id

    await event_store.record(
        db,
        event_type="batch.assigned",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="batch",
        target_id=batch.id,
        payload={
            "batch_id": batch.id,
            "worker_id": worker_id,
            "worker_name": worker.name,
        },
    )

    return batch
