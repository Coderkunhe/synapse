"""Task depends_on 校验 — P9-B7.

create_task 时对 depends_on 字段的三段校验：
(a) 重复 ID 检测
(b) task_id 存在性 + 同 project
(c) 循环依赖检测（BFS, 深度上限 10）
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import ConflictError, NotFoundError
from src.models.task import Task
from src.utils.json_utils import safe_loads


async def validate_depends_on(
    db: AsyncSession,
    depends_on: list[dict],
    project_id: str,
) -> None:
    """校验 depends_on 列表的有效性。

    Raises:
        ConflictError: 重复 ID / 跨 project / 循环依赖
        NotFoundError: 依赖 task 不存在
    """
    dep_ids = [d["task_id"] for d in depends_on]

    # (a) 重复 ID 检测
    if len(set(dep_ids)) != len(dep_ids):
        raise ConflictError(
            "DUPLICATE_DEPENDENCY",
            "Duplicate dependency task IDs are not allowed",
        )

    # (b) task_id 存在性 + 同 project
    for dep in depends_on:
        dep_task = await db.get(Task, dep["task_id"])
        if dep_task is None:
            raise NotFoundError("task", dep["task_id"])
        if dep_task.project_id != project_id:
            raise ConflictError(
                "DEPENDENCY_PROJECT_MISMATCH",
                f"Dependency task {dep['task_id']} must belong to the same project",
                {"dependencyTaskId": dep["task_id"], "projectId": project_id},
            )

    # (c) 循环依赖检测 — BFS 沿 depends_on 链追溯
    for dep_id in dep_ids:
        visited: set[str] = set()
        queue: list[str] = [dep_id]
        depth = 0
        while queue and depth < 10:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            current_task = await db.get(Task, current_id)
            if current_task is None:
                continue
            current_deps = safe_loads(current_task.depends_on) or []
            for d in current_deps:
                nid = d["task_id"]
                if nid == dep_id:
                    raise ConflictError(
                        "CIRCULAR_DEPENDENCY",
                        f"Circular dependency detected: task {dep_id} "
                        f"transitively depends on itself via {current_id}",
                        {"taskId": dep_id, "viaTaskId": current_id},
                    )
                if nid not in visited:
                    queue.append(nid)
            depth += 1
