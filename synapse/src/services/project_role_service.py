"""Project Actor Role 服务 — project_actor_roles 表的 CRUD + 事件记录。

P10-B18: 议题 3 授权管道 — project_actor_roles 首次接线。
ADR-004 解析链路：SELECT role FROM project_actor_roles WHERE worker_id=? AND project_id=?

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import EventType
from src.exceptions import ConflictError
from src.models.project import Project
from src.models.project_actor_role import ProjectActorRole
from src.models.worker import Worker
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ── 查询 ──────────────────────────────────────────────────────────


async def get_project_role(
    db: AsyncSession,
    project_id: str,
    worker_id: str,
) -> str | None:
    """获取 Worker 在 Project 中的角色。无记录返回 None。"""
    result = await db.execute(
        select(ProjectActorRole.role).where(
            ProjectActorRole.project_id == project_id,
            ProjectActorRole.worker_id == worker_id,
        )
    )
    return result.scalar_one_or_none()


async def list_project_roles(
    db: AsyncSession,
    project_id: str,
) -> list[tuple[Worker, str]]:
    """列出 Project 中所有 Worker 及其角色。

    Returns:
        [(Worker, role_str), ...] 按 worker name 排序。
    """
    result = await db.execute(
        select(Worker, ProjectActorRole.role)
        .join(ProjectActorRole, ProjectActorRole.worker_id == Worker.id)
        .where(ProjectActorRole.project_id == project_id)
        .order_by(Worker.name)
    )
    rows = result.all()
    return [(row.Worker, row.role) for row in rows]


async def get_worker_projects(
    db: AsyncSession,
    worker_id: str,
) -> list[dict]:
    """Return all projects the worker belongs to via project_actor_roles.

    Each dict contains basic project info plus the worker's role in that project.
    Used by ``GET /workers/me/projects`` for project discovery (P11-B9).
    """
    result = await db.execute(
        select(Project, ProjectActorRole.role)
        .join(ProjectActorRole, ProjectActorRole.project_id == Project.id)
        .where(ProjectActorRole.worker_id == worker_id)
        .order_by(Project.name)
    )
    rows = result.all()
    return [
        {
            "project_id": row.Project.id,
            "name": row.Project.name,
            "display_name": row.Project.display_name,
            "role": row.role,
            "has_project_key": row.Project.project_key_hash is not None,
        }
        for row in rows
    ]


# ── 写入 ──────────────────────────────────────────────────────────


async def set_project_role(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    role: str,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> ProjectActorRole:
    """为 Worker 分配或更新 Project 内角色（upsert）。

    使用唯一约束 (project_id, worker_id) 做 ON CONFLICT 语义：
    已存在 → 更新 role；不存在 → 创建新记录。
    角色变更时记录 ``worker.project_role_changed`` 事件。

    Raises:
        ConflictError: 若 role="orchestrator" 且该 Project 已有其他 orchestrator。
    """
    # 1-O constraint: at most one Orchestrator per Project
    # (temporary simplification; will be upgraded to per-Workflow when Workflow recursion lands)
    if role == "orchestrator":
        existing_orch = await db.execute(
            select(ProjectActorRole).where(
                ProjectActorRole.project_id == project_id,
                ProjectActorRole.role == "orchestrator",
                ProjectActorRole.worker_id != worker_id,
            )
        )
        if existing_orch.scalar_one_or_none():
            raise ConflictError(
                "ONE_ORCHESTRATOR_PER_PROJECT",
                f"Project {project_id} already has an orchestrator. "
                "Only one orchestrator is allowed per project.",
            )

    # 检查现有记录
    result = await db.execute(
        select(ProjectActorRole).where(
            ProjectActorRole.project_id == project_id,
            ProjectActorRole.worker_id == worker_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is None:
        # 新建
        record = ProjectActorRole(
            id=generate_id("project_actor_role"),
            project_id=project_id,
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
        event_type=EventType.WORKER_PROJECT_ROLE_CHANGED
        if not is_new
        else EventType.WORKER_PROJECT_ROLE_ASSIGNED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="project_actor_role",
        target_id=record.id,
        payload={
            "project_id": project_id,
            "worker_id": worker_id,
            "role": role,
            "action": "assign" if is_new else "update",
        },
    )

    return record


async def remove_project_role(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> bool:
    """移除 Worker 在 Project 中的角色。

    Returns:
        True 如果删除了记录，False 如果没有记录。
    """
    result = await db.execute(
        select(ProjectActorRole).where(
            ProjectActorRole.project_id == project_id,
            ProjectActorRole.worker_id == worker_id,
        )
    )
    record = result.scalar_one_or_none()

    if record is None:
        return False

    await db.delete(record)
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.WORKER_PROJECT_ROLE_REVOKED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="project_actor_role",
        target_id=record.id,
        payload={
            "project_id": project_id,
            "worker_id": worker_id,
            "role": record.role,
        },
    )

    return True
