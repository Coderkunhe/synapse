"""Dependency chain resolution — recursive upstream/downstream traversal.

P12-B43: Resolve the full transitive dependency chain for a single Task,
traversing both upstream (tasks this task depends on) and downstream
(tasks that depend on this task).

Uses BFS with a depth cap (10) and cycle detection (visited set) to
protect against infinite recursion on malformed data.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import Task


MAX_DEPTH = 10


async def _parse_depends_on(task: Task) -> list[dict]:
    """Safely parse the depends_on JSON column."""
    if not task.depends_on:
        return []
    try:
        deps = json.loads(task.depends_on)
        if not isinstance(deps, list):
            return []
        return deps
    except (json.JSONDecodeError, TypeError):
        return []


async def get_upstream_chain(
    db: AsyncSession,
    task_id: str,
    *,
    max_depth: int = MAX_DEPTH,
) -> list[dict]:
    """Recursively resolve all upstream dependencies (BFS).

    Follows ``depends_on`` links upward — returns every task that the
    given task transitively depends on, ordered by traversal depth.
    Includes the direct dependency ``type`` from the immediate child.
    """
    result: list[dict] = []
    visited: set[str] = {task_id}
    # queue items: (child_task_id, task_id_to_explore)
    queue: list[tuple[str | None, str]] = [(None, task_id)]

    depth = 0
    while queue and depth < max_depth:
        parent_id, current_id = queue.pop(0)
        current = await db.get(Task, current_id)
        if current is None:
            continue

        deps = await _parse_depends_on(current)
        for dep in deps:
            dep_id = dep.get("task_id")
            if not dep_id or dep_id in visited:
                continue
            visited.add(dep_id)

            dep_task = await db.get(Task, dep_id)
            item = {
                "task_id": dep_id,
                "title": dep_task.title if dep_task else "(deleted)",
                "status": dep_task.status if dep_task else "unknown",
                "dependency_type": dep.get("type", "sequential"),
            }
            result.append(item)
            queue.append((current_id, dep_id))

        depth += 1

    return result


async def get_downstream_chain(
    db: AsyncSession,
    task_id: str,
    *,
    max_depth: int = MAX_DEPTH,
) -> list[dict]:
    """Recursively resolve all downstream dependents (BFS).

    Finds every task whose ``depends_on`` includes the given task,
    then repeats for each found task.  Returns the full transitive
    closure of dependents.
    """
    if not task_id:
        return []

    result: list[dict] = []
    visited: set[str] = {task_id}
    queue: list[str] = [task_id]

    depth = 0
    while queue and depth < max_depth:
        current_id = queue.pop(0)

        # Find all tasks in the same project whose depends_on contains current_id.
        # We load the project-scoped candidates to avoid a table scan.
        current = await db.get(Task, current_id)
        if current is None:
            continue

        rows = await db.execute(
            select(Task).where(
                Task.project_id == current.project_id,
                Task.depends_on.isnot(None),
                Task.depends_on != "[]",
                Task.depends_on != "null",
            )
        )
        candidates = rows.scalars().all()

        for candidate in candidates:
            if candidate.id in visited:
                continue
            deps = await _parse_depends_on(candidate)
            for dep in deps:
                dep_id = dep.get("task_id")
                if dep_id == current_id:
                    visited.add(candidate.id)
                    item = {
                        "task_id": candidate.id,
                        "title": candidate.title,
                        "status": candidate.status,
                        "dependency_type": dep.get("type", "sequential"),
                    }
                    result.append(item)
                    queue.append(candidate.id)
                    break

        depth += 1

    return result


async def get_dependency_chain(
    db: AsyncSession,
    task_id: str,
    direction: str = "both",
) -> dict:
    """Return the full dependency chain for a task.

    Args:
        db: Async database session.
        task_id: The task to resolve.
        direction: ``"upstream"``, ``"downstream"``, or ``"both"``.

    Returns:
        ``{"task_id": str, "chain": {"upstream": [...], "downstream": [...]}}``
    """
    upstream: list[dict] = []
    downstream: list[dict] = []

    if direction in ("upstream", "both"):
        upstream = await get_upstream_chain(db, task_id)

    if direction in ("downstream", "both"):
        downstream = await get_downstream_chain(db, task_id)

    return {
        "task_id": task_id,
        "chain": {
            "upstream": upstream,
            "downstream": downstream,
        },
    }
