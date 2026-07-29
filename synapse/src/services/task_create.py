"""Task 创建服务 — create_task + 关联 Verification 创建。

调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import TaskStatus, VerificationStatus
from src.exceptions import (
    ConflictError,
    NotFoundError,
)
from src.models.project import Project
from src.models.task import Task
from src.models.verification import Verification
from src.services.event_store import event_store
from src.services.ws_manager import ws_manager
from src.utils.id_gen import generate_id
from src.utils.json_utils import safe_dumps


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
    required_capabilities: list[str] | None = None,
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
        required_capabilities=safe_dumps(required_capabilities),
        metadata_=safe_dumps(metadata),
        depends_on=safe_dumps(depends_on),
        deadline_at=deadline_at,
        create_user_id=actor_id,
    )
    db.add(task)

    # 创建验证记录
    verification_objs = []
    for v in verifications:
        # P11-B70: expected_evidence_type 存入 criteria JSON（零 migration）
        criteria = v.get("criteria") or {}
        ee_type = v.get("expected_evidence_type")
        if ee_type is not None:
            criteria = {**criteria, "_expected_evidence_type": ee_type}
        ver = Verification(
            id=generate_id("verification"),
            task_id=task.id,
            type=v["type"],
            description=v["description"],
            criteria=safe_dumps(criteria) if criteria else None,
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

    # P11-B21 PFL-041: WS push — notify creator
    await ws_manager.broadcast_to_actor(
        actor_id,
        {
            "type": "event",
            "data": {
                "event_type": "task.created",
                "task_id": task.id,
                "status": task.status,
                "title": title,
            },
        },
    )

    return task
