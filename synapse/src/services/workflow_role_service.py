"""Workflow + WorkflowRole 服务 — CRUD + 事件记录。

P10-B25: 议题 4 per-Workflow 角色 — Service 层。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import EventType
from src.models.workflow import Workflow, WorkflowRole
from src.models.worker import Worker
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ═══════════════════════════════════════════════════════════════
# Workflow CRUD
# ═══════════════════════════════════════════════════════════════


async def create_workflow(
    db: AsyncSession,
    *,
    project_id: str,
    name: str,
    description: str | None = None,
    status: str = "active",
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> Workflow:
    """创建 Workflow — Project 内的协调上下文。

    自动生成 ``wfl_`` 前缀 ID，记录 ``workflow.created`` 事件。
    """
    workflow = Workflow(
        id=generate_id("workflow"),
        project_id=project_id,
        name=name,
        description=description,
        status=status,
    )
    db.add(workflow)
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.WORKFLOW_CREATED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="workflow",
        target_id=workflow.id,
        payload={
            "project_id": project_id,
            "name": name,
            "description": description,
            "status": status,
        },
    )

    return workflow


async def get_workflow(
    db: AsyncSession,
    workflow_id: str,
) -> Workflow | None:
    """按 ID 获取 Workflow。无记录返回 None。"""
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id)
    )
    return result.scalar_one_or_none()


async def list_workflows(
    db: AsyncSession,
    project_id: str,
) -> list[Workflow]:
    """列出 Project 中所有 Workflow，按创建时间倒序。"""
    result = await db.execute(
        select(Workflow)
        .where(Workflow.project_id == project_id)
        .order_by(Workflow.created_at.desc())
    )
    return list(result.scalars().all())


async def update_workflow(
    db: AsyncSession,
    *,
    workflow_id: str,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> Workflow | None:
    """更新 Workflow 字段。只更新显式传入的非 None 字段。

    Returns:
        Workflow 或 None（如果找不到）。
    """
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        return None

    changes: dict = {}

    if name is not None:
        workflow.name = name
        changes["name"] = name
    if description is not None:
        workflow.description = description
        changes["description"] = description
    if status is not None:
        workflow.status = status
        changes["status"] = status

    if not changes:
        return workflow  # 没有要更新的内容

    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.WORKFLOW_UPDATED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="workflow",
        target_id=workflow.id,
        payload={
            "project_id": workflow.project_id,
            "changes": changes,
        },
    )

    return workflow


async def complete_workflow(
    db: AsyncSession,
    *,
    workflow_id: str,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> Workflow | None:
    """将 Workflow 标记为 completed。

    Returns:
        Workflow 或 None（如果找不到）。
    """
    workflow = await get_workflow(db, workflow_id)
    if workflow is None:
        return None

    workflow.status = "completed"
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.WORKFLOW_COMPLETED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="workflow",
        target_id=workflow.id,
        payload={
            "project_id": workflow.project_id,
            "name": workflow.name,
        },
    )

    return workflow


# ═══════════════════════════════════════════════════════════════
# WorkflowRole CRUD
# ═══════════════════════════════════════════════════════════════


async def assign_workflow_role(
    db: AsyncSession,
    *,
    workflow_id: str,
    worker_id: str,
    role: str,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> WorkflowRole:
    """为 Worker 在 Workflow 中分配或更新角色（upsert）。

    使用唯一约束 ``(workflow_id, worker_id)`` 做 upsert：
    已存在且角色不同 → 更新；已存在且角色相同 → 无操作；
    不存在 → 创建新记录。
    """
    # 检查现有记录
    result = await db.execute(
        select(WorkflowRole).where(
            WorkflowRole.workflow_id == workflow_id,
            WorkflowRole.worker_id == worker_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is None:
        # 新建
        record = WorkflowRole(
            id=generate_id("workflow_role"),
            workflow_id=workflow_id,
            worker_id=worker_id,
            role=role,
        )
        db.add(record)
        is_new = True
    elif existing.role != role:
        # 更新角色
        existing.role = role
        record = existing
        is_new = False
    else:
        # 角色未变，无需操作
        return existing

    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.WORKFLOW_ROLE_CHANGED
        if not is_new
        else EventType.WORKFLOW_ROLE_ASSIGNED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="workflow_role",
        target_id=record.id,
        payload={
            "workflow_id": workflow_id,
            "worker_id": worker_id,
            "role": role,
            "action": "assign" if is_new else "update",
        },
    )

    return record


async def list_workflow_roles(
    db: AsyncSession,
    workflow_id: str,
) -> list[tuple[Worker, str]]:
    """列出 Workflow 中所有 Worker 及其角色。

    Returns:
        [(Worker, role_str), ...] 按 worker name 排序。
    """
    result = await db.execute(
        select(Worker, WorkflowRole.role)
        .join(WorkflowRole, WorkflowRole.worker_id == Worker.id)
        .where(WorkflowRole.workflow_id == workflow_id)
        .order_by(Worker.name)
    )
    rows = result.all()
    return [(row.Worker, row.role) for row in rows]


async def revoke_workflow_role(
    db: AsyncSession,
    *,
    workflow_id: str,
    worker_id: str,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> bool:
    """移除 Worker 在 Workflow 中的角色。

    Returns:
        True 如果删除了记录，False 如果没有记录。
    """
    result = await db.execute(
        select(WorkflowRole).where(
            WorkflowRole.workflow_id == workflow_id,
            WorkflowRole.worker_id == worker_id,
        )
    )
    record = result.scalar_one_or_none()

    if record is None:
        return False

    await db.delete(record)
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.WORKFLOW_ROLE_REVOKED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="workflow_role",
        target_id=record.id,
        payload={
            "workflow_id": workflow_id,
            "worker_id": worker_id,
            "role": record.role,
        },
    )

    return True
