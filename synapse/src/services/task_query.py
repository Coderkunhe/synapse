"""Task 查询服务 — 从 task_service.py 拆出的只读查询。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import TaskStatus
from src.exceptions import NotFoundError
from src.models.project import Project
from src.models.task import Task
from src.utils.json_utils import safe_loads


async def get_available_tasks(db, project_id, *, capability=None, cursor=None, limit=50,
                              hide_dependency_blocked: bool = True):
    """获取项目中状态为 ready 的可领取 Task，游标分页。

    可按 ``capability``（验证类型）过滤。
    ``hide_dependency_blocked`` (P12-B33 G4) 默认过滤仍有未完成依赖的 Task。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)
    conditions = [Task.project_id == project_id, Task.status == TaskStatus.READY]
    if cursor:
        conditions.append(Task.id > cursor)
    stmt = select(Task).where(*conditions).order_by(Task.id).limit(limit + 1)
    if capability:
        from src.models.verification import Verification as V
        mids = select(V.task_id).where(V.type == capability).distinct()
        stmt = stmt.where(Task.id.in_(mids))
    result = await db.execute(stmt)
    rows = result.scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    # P12-B33 G4: filter out tasks with unmet dependencies
    # A task is "dependency blocked" when depends_on is non-empty and any
    # dependency is not COMPLETED. Such tasks cannot be claimed (409).
    if hide_dependency_blocked:
        items = await filter_dependency_blocked(db, items)

    count_stmt = select(func.count(Task.id)).where(*conditions)
    if capability:
        count_stmt = count_stmt.where(Task.id.in_(mids))
    total = (await db.execute(count_stmt)).scalar()
    return items, next_cursor, total


async def filter_dependency_blocked(
    db: AsyncSession,
    tasks: list[Task],
) -> list[Task]:
    """Remove tasks whose ``depends_on`` references are not all COMPLETED.

    P12-B33 G4: A task with unmet dependencies is not truly "available"
    because claiming it will return 409 TASK_DEPENDENCY_NOT_READY.

    P16-B5 (PFL-248): 公开给 ``state_router`` 复用——「什么叫 dependency
    blocked」必须只有一个定义。端点层拦了但路由层还把它当 ready，O/B 就会
    在同一个不可操作的任务上空转（B4 狗粮实测）。
    """
    from src.models.task import Task as T

    filtered: list[T] = []
    for task in tasks:
        if not task.depends_on:
            filtered.append(task)
            continue
        deps = safe_loads(task.depends_on)
        if not deps:
            filtered.append(task)
            continue
        all_met = True
        for dep in deps:
            dep_task = await db.get(T, dep["task_id"])
            if dep_task is None or dep_task.status != TaskStatus.COMPLETED:
                all_met = False
                break
        if all_met:
            filtered.append(task)
    return filtered


async def get_tasks(db, project_id, *, status=None, owner_id=None,
                    batch_id=None, search=None, cursor=None, limit=50):
    """获取项目中所有 Task，可选过滤，游标分页。

    与 ``get_available_tasks`` 不同：默认不过滤 status，返回所有状态的 Task。
    ``status`` 接受 TaskStatus 值或特殊值 ``"overdue"``（deadline 已过且未完成/取消的任务）。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)
    conditions = [Task.project_id == project_id]
    if status == "overdue":
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        conditions.append(Task.deadline_at.isnot(None))
        conditions.append(Task.deadline_at < now)
        conditions.append(Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]))
    elif status:
        conditions.append(Task.status == status)
    if owner_id:
        conditions.append(Task.owner_id == owner_id)
    if batch_id:
        conditions.append(Task.batch_id == batch_id)
    if search:
        conditions.append(
            (Task.title.ilike(f'%{search}%')) | (Task.id.ilike(f'{search}%'))
        )
    if cursor:
        conditions.append(Task.id > cursor)
    stmt = select(Task).where(*conditions).order_by(Task.id).limit(limit + 1)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None
    count_stmt = select(func.count(Task.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar()
    return items, next_cursor, total
