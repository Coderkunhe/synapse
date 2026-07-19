"""Project 服务 — CRUD + 归档 + 事件记录 + resolve-by-name。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ProjectStatus
from src.exceptions import ConflictError, NotFoundError
from src.models.project import Project
from src.services.event_store import event_store
from src.services.project_role_service import set_project_role
from src.utils.id_gen import generate_id
from src.utils.json_utils import safe_dumps, safe_loads


def _name_to_slug(name: str) -> str:
    """将项目名转换为 URL 友好的 slug。"""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")[:200]
    return slug or "project"


async def create_project(
    db: AsyncSession,
    *,
    team_id: str,
    name: str,
    slug: str,
    description: str | None,
    default_branch: str | None,
    git_repo_url: str | None,
    api_docs_url: str | None = None,
    frontend_test_url: str | None = None,
    webhook_url: str | None = None,
    use_phase_mode: bool = False,
    current_phase: str | None = None,
    organization: str | None = None,
    metadata: dict | None,
    is_protected: bool = False,
    actor_type: str,
    actor_id: str,
) -> Project:
    """为团队创建 Project。检查团队内 slug 唯一性。

    记录 ``project.created`` 事件。
    """
    # Slug 唯一性检查
    existing = await db.execute(
        select(Project).where(
            Project.team_id == team_id,
            Project.slug == slug,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(
            "PROJECT_SLUG_EXISTS",
            f"Project slug '{slug}' already exists in team {team_id}",
        )

    project = Project(
        id=generate_id("project"),
        team_id=team_id,
        name=name,
        slug=slug,
        description=description,
        default_branch=default_branch,
        git_repo_url=git_repo_url,
        api_docs_url=api_docs_url,
        frontend_test_url=frontend_test_url,
        webhook_url=webhook_url,
        use_phase_mode=use_phase_mode,
        current_phase=current_phase,
        organization=organization,
        metadata_=safe_dumps(metadata),
        is_protected=is_protected,
        create_user_id=actor_id,
    )
    db.add(project)

    await event_store.record(
        db,
        event_type="project.created",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="project",
        target_id=project.id,
        payload={"name": name, "slug": slug, "status": ProjectStatus.ACTIVE},
    )

    # P10-B19: 创建者自动获得项目 admin 角色
    await set_project_role(
        db,
        project_id=project.id,
        worker_id=actor_id,
        role="admin",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return project


async def list_projects(
    db: AsyncSession,
    team_id: str,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Project], str | None, int]:
    """列出团队的项目，游标分页（按 created_at 降序）。"""
    query = (
        select(Project)
        .where(Project.team_id == team_id)
        .order_by(Project.created_at.desc())
    )
    # 计数总数
    count_query = select(Project).where(Project.team_id == team_id)
    total_result = await db.execute(count_query)
    total = len(total_result.scalars().all())

    # 游标分页：created_at DESC + id 作为 tiebreaker
    if cursor:
        cursor_stmt = select(Project.created_at, Project.id).where(Project.id == cursor)
        cursor_result = await db.execute(cursor_stmt)
        cursor_row = cursor_result.one_or_none()
        if cursor_row:
            cursor_ts, _ = cursor_row
            query = query.where(
                (Project.created_at < cursor_ts)
                | ((Project.created_at == cursor_ts) & (Project.id < cursor))
            )

    query = query.limit(limit + 1)
    result = await db.execute(query)
    rows = result.scalars().all()

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].id

    return list(rows), next_cursor, total


async def get_project(db: AsyncSession, project_id: str) -> Project:
    """按 ID 获取项目，不存在则抛出 NotFoundError。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)
    return project


async def update_project(
    db: AsyncSession,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    default_branch: str | None = None,
    git_repo_url: str | None = None,
    api_docs_url: str | None = None,
    frontend_test_url: str | None = None,
    webhook_url: str | None = None,
    use_phase_mode: bool | None = None,
    current_phase: str | None = None,
    organization: str | None = None,
    metadata: dict | None = None,
    is_protected: bool | None = None,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Project:
    """更新项目字段。仅非 None 字段会被修改。

    如有字段变更则记录 ``project.updated`` 事件。
    """
    project = await get_project(db, project_id)

    changed = False
    if name is not None:
        project.name = name
        changed = True
    if description is not None:
        project.description = description
        changed = True
    if default_branch is not None:
        project.default_branch = default_branch
        changed = True
    if git_repo_url is not None:
        project.git_repo_url = git_repo_url
        changed = True
    if api_docs_url is not None:
        project.api_docs_url = api_docs_url
        changed = True
    if frontend_test_url is not None:
        project.frontend_test_url = frontend_test_url
        changed = True
    if webhook_url is not None:
        project.webhook_url = webhook_url
        changed = True
    if use_phase_mode is not None:
        project.use_phase_mode = use_phase_mode
        changed = True
    if current_phase is not None:
        project.current_phase = current_phase
        changed = True
    if organization is not None:
        project.organization = organization
        changed = True
    if metadata is not None:
        project.metadata_ = safe_dumps(metadata)
        changed = True
    if is_protected is not None:
        project.is_protected = is_protected
        changed = True

    if changed:
        await event_store.record(
            db,
            event_type="project.updated",
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="project",
            target_id=project.id,
            payload={"status": project.status},
        )

    return project


async def archive_project(
    db: AsyncSession,
    project_id: str,
    *,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Project:
    """归档项目。受保护项目或已归档项目抛出 ConflictError。

    记录 ``project.archived`` 事件。
    """
    project = await get_project(db, project_id)

    if project.is_protected:
        raise ConflictError(
            "PROJECT_PROTECTED",
            f"Project {project_id} is protected — unprotect before archiving",
        )

    if project.status == ProjectStatus.ARCHIVED:
        raise ConflictError(
            "PROJECT_ALREADY_ARCHIVED",
            f"Project {project_id} is already archived",
        )

    previous_status = project.status
    project.status = ProjectStatus.ARCHIVED
    project.archived_at = datetime.now(timezone.utc)

    await event_store.record(
        db,
        event_type="project.archived",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="project",
        target_id=project.id,
        payload={
            "previous_status": previous_status,
            "new_status": ProjectStatus.ARCHIVED,
        },
    )

    return project


async def toggle_protection(
    db: AsyncSession,
    project_id: str,
    *,
    is_protected: bool,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Project:
    """切换项目的防误删保护标记。

    记录 ``project.protection_toggled`` 事件。
    """
    project = await get_project(db, project_id)

    if project.is_protected == is_protected:
        # 幂等 — 已经是目标状态
        return project

    project.is_protected = is_protected

    await event_store.record(
        db,
        event_type="project.protection_toggled",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="project",
        target_id=project.id,
        payload={"is_protected": is_protected},
    )

    return project


async def delete_project(
    db: AsyncSession,
    project_id: str,
    *,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> None:
    """硬删除项目。

    前置条件（任一不满足 → ConflictError）：
    1. status == ProjectStatus.ARCHIVED — 必须先归档
    2. archived_at + 7 days < now() — 冷静期未满
    3. is_protected == False — 受保护项目不可删除

    删除前自动调用 db-backup.sh 做安全备份。
    记录 ``project.deleted`` 事件后从 DB 移除。
    """
    project = await get_project(db, project_id)

    if project.is_protected:
        raise ConflictError(
            "PROJECT_PROTECTED",
            f"Project {project_id} is protected — unprotect before deleting",
        )

    if project.status != ProjectStatus.ARCHIVED:
        raise ConflictError(
            "PROJECT_NOT_ARCHIVED",
            f"Project {project_id} must be archived before deletion",
        )

    if project.archived_at is None:
        raise ConflictError(
            "PROJECT_NO_ARCHIVE_DATE",
            f"Project {project_id} has no archive date — please re-archive",
        )

    cooldown_deadline = project.archived_at + timedelta(days=7)
    if datetime.now(timezone.utc) < cooldown_deadline:
        remaining = cooldown_deadline - datetime.now(timezone.utc)
        days_left = remaining.days + (1 if remaining.seconds > 0 else 0)
        raise ConflictError(
            "PROJECT_COOLDOWN_ACTIVE",
            f"Project {project_id} cooldown active — {days_left} day(s) remaining before deletion",
        )

    # 安全备份
    _run_db_backup(f"before-delete-{project_id}")

    # 记录删除事件
    await event_store.record(
        db,
        event_type="project.deleted",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="project",
        target_id=project.id,
        payload={
            "name": project.name,
            "slug": project.slug,
            "status": project.status,
            "archived_at": project.archived_at.isoformat() if project.archived_at else None,
        },
    )

    await db.delete(project)


def _run_db_backup(label: str) -> None:
    """调用 db-backup.sh 做安全备份。失败不阻断（仅 log）。"""
    import logging
    import os

    logger = logging.getLogger(__name__)
    script_dir = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
    script_path = os.path.join(script_dir, "db-backup.sh")

    try:
        subprocess.run(
            ["bash", script_path, label],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        logger.warning("db-backup.sh failed for label=%s — proceeding with delete", label)


async def find_or_create_by_name(
    db: AsyncSession,
    *,
    team_id: str,
    name: str,
    actor_type: str,
    actor_id: str,
) -> Project:
    """按名称查找项目，不存在则自动创建。

    P9-B1: Task 入口放松 — Project 退化为可选标签。
    用户输入 project name → resolve 为 project_id，首次自动创建。
    """
    # 精确名称匹配
    result = await db.execute(
        select(Project).where(
            Project.team_id == team_id,
            Project.name == name,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    # 自动创建 — slug 由 name 生成，冲突时追加短随机串
    slug = _name_to_slug(name)
    conflict_result = await db.execute(
        select(Project).where(
            Project.team_id == team_id,
            Project.slug == slug,
        )
    )
    if conflict_result.scalar_one_or_none():
        slug = f"{slug}-{generate_id('project').replace('_', '')[-6:]}"

    project = Project(
        id=generate_id("project"),
        team_id=team_id,
        name=name,
        slug=slug,
        create_user_id=actor_id,
    )
    db.add(project)

    await event_store.record(
        db,
        event_type="project.created",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="project",
        target_id=project.id,
        payload={"name": name, "slug": slug, "status": ProjectStatus.ACTIVE,
                  "source": "resolve"},
    )

    # P10-B19: 创建者自动获得项目 admin 角色
    await set_project_role(
        db,
        project_id=project.id,
        worker_id=actor_id,
        role="admin",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return project


def project_to_response(project: Project) -> dict:
    """将 Project ORM 对象转换为响应字典，含 JSON 反序列化。"""
    return {
        "id": project.id,
        "team_id": project.team_id,
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "status": project.status,
        "default_branch": project.default_branch,
        "git_repo_url": project.git_repo_url,
        "api_docs_url": project.api_docs_url,
        "frontend_test_url": project.frontend_test_url,
        "webhook_url": project.webhook_url,
        "use_phase_mode": project.use_phase_mode,
        "current_phase": project.current_phase,
        "organization": project.organization,
        "metadata": safe_loads(project.metadata_),
        "is_protected": project.is_protected,
        "archived_at": project.archived_at,
        "is_disabled": project.is_disabled,
        "create_user_id": project.create_user_id,
        "last_update_user_id": project.last_update_user_id,
        "remark": project.remark,
        "version_no": project.version_no,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
