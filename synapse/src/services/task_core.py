"""Task 核心服务 — 共享 helper + 基础 CRUD + 响应序列化。

所有状态变更函数依赖本模块的 helper。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func as sa_func, select as sa_select
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import OwnerType, TaskStatus
from src.exceptions import (
    ConflictError,
    InvalidStateTransition,
    NotFoundError,
)
from src.models.authorization_request import AuthorizationRequest
from src.models.task import Task
from src.models.verification import Verification
from src.services.event_store import event_store
from src.services.ws_manager import ws_manager
from src.utils.json_utils import safe_dumps, safe_loads


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


async def _check_no_pending_auth(
    db: AsyncSession,
    *,
    task_id: str,
    actor_id: str,
) -> None:
    """PFL-046: 若存在该 Worker 对此 Task 的 pending 授权请求，硬拒绝 409。

    在每次 mutation（assign/claim/submit/cancel/ready/pause/resume/terminate）
    前调用。防止 Worker 在授权审批 pending 期间绕过审批直接操作。
    """
    result = await db.execute(
        select(AuthorizationRequest).where(
            AuthorizationRequest.worker_id == actor_id,
            AuthorizationRequest.target_resource_type == "task",
            AuthorizationRequest.target_resource_id == task_id,
            AuthorizationRequest.status == "pending",
        )
    )
    pending = result.scalars().all()
    if pending:
        request_ids = [r.id for r in pending]
        raise ConflictError(
            "PENDING_AUTHORIZATION",
            f"Worker {actor_id} has {len(pending)} pending authorization "
            f"request(s) for Task {task_id}: {request_ids}. "
            f"Wait for approval before retrying this operation.",
            {
                "pendingRequestIds": request_ids,
                "taskId": task_id,
                "workerId": actor_id,
            },
        )


# ── 状态机 ─────────────────────────────────────────────────

def _validate_transition(task: Task, new_status: str) -> None:
    allowed = Task.ALLOWED_TRANSITIONS.get(task.status, frozenset())
    if new_status not in allowed:
        raise InvalidStateTransition("task", task.id, task.status, new_status)


# ── Task CRUD helpers ────────────────────────────────────

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
    required_capabilities: list[str] | None = None,
    metadata: dict | None,
    deadline_at: datetime | None,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)

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
    if required_capabilities is not None:
        task.required_capabilities = safe_dumps(required_capabilities)
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


# ── Verification helpers ─────────────────────────────────

async def _count_verifications(db: AsyncSession, task_id: str) -> int:
    """返回任务的验证记录数量。"""
    result = await db.execute(
        sa_select(sa_func.count(Verification.id)).where(Verification.task_id == task_id)
    )
    return result.scalar() or 0


async def _get_verifications(db: AsyncSession, task_id: str) -> list[Verification]:
    """返回任务的验证记录列表（P11-B70）。"""
    result = await db.execute(
        select(Verification).where(Verification.task_id == task_id)
    )
    return list(result.scalars().all())


# ── 响应序列化 ───────────────────────────────────────────

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
        "required_capabilities": safe_loads(task.required_capabilities),
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
