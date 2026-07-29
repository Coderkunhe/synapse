"""CapabilityAudit API 端点 — 能力执行审计查询 + 创建。

P11-B57 (GAP-8): 只读查询端点，审计记录不可变。
P11-B100 (GAP-8 补刀): 安全命令审计持久化 — POST 端点。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.permissions import require_permission
from src.models.capability_audit import CapabilityAudit
from src.models.worker import Worker
from src.schemas.capability_audit import (
    CapabilityAuditCreate,
    CapabilityAuditPage,
    CapabilityAuditResponse,
)
from src.services.capability_audit_service import (
    list_capability_audits,
    write_capability_audit,
)

from .helpers import get_project_or_404

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# POST /projects/{project_id}/capability-audits
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/projects/{project_id}/capability-audits",
    response_model=CapabilityAuditResponse,
    status_code=201,
)
async def create_capability_audit(
    project_id: str,
    body: CapabilityAuditCreate,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """创建能力执行审计记录 — P11-B100。

    Worker 在 capability 执行完成后调用此端点持久化审计记录。
    覆盖两条路径：
    - 安全命令（免审批）：authorization_request_id 为 null
    - 授权命令：传入 authorization_request_id 关联授权请求

    worker_id 从认证 actor 自动提取，Worker 只能上报自己的执行记录。
    """
    await get_project_or_404(db, project_id)

    audit = await write_capability_audit(
        db,
        project_id=project_id,
        worker_id=actor.actor_id,
        capability_id=body.capability_id,
        authorization_request_id=body.authorization_request_id,
        exit_code=body.exit_code,
        duration_ms=body.duration_ms,
        outcome=body.outcome,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        command=body.command,
    )
    # write_capability_audit 内部调用了 db.flush()，这里 commit
    await db.commit()

    # 富化 worker_name
    result = await db.execute(
        select(Worker.name).where(Worker.id == actor.actor_id)
    )
    worker_name = result.scalar_one_or_none()

    return CapabilityAuditResponse(
        id=audit.id,
        project_id=audit.project_id,
        worker_id=audit.worker_id,
        capability_id=audit.capability_id,
        authorization_request_id=audit.authorization_request_id,
        command=audit.command,
        exit_code=audit.exit_code,
        duration_ms=audit.duration_ms,
        outcome=audit.outcome,
        actor_type=audit.actor_type,
        actor_id=audit.actor_id,
        created_at=audit.created_at,
        worker_name=worker_name,
    )


# ═══════════════════════════════════════════════════════════════════
# GET /projects/{project_id}/capability-audits
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/capability-audits",
    response_model=CapabilityAuditPage,
)
async def list_project_capability_audits(
    project_id: str,
    worker_id: str | None = Query(None, description="按 Worker 过滤"),
    capability_id: str | None = Query(None, description="按 capability 过滤（如 shell_dangerous）"),
    outcome: str | None = Query(None, pattern=r"^(success|failure)$", description="按结果过滤"),
    date_from: str | None = Query(None, description="起始日期 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="截止日期 (YYYY-MM-DD)"),
    cursor: str | None = Query(None, max_length=80, description="分页游标"),
    limit: int = Query(50, ge=1, le=100, description="每页条数"),
    actor: ActorInfo = Depends(require_permission("capability_audit:read")),
    db: AsyncSession = Depends(get_db),
):
    """查询项目下 capability 执行审计记录。

    需要 admin/lead 角色。按执行时间降序排列。
    支持按 Worker、capability、执行结果、日期范围过滤。
    使用 cursor-based 分页。
    """
    await get_project_or_404(db, project_id)

    items, next_cursor, total = await list_capability_audits(
        db,
        project_id=project_id,
        worker_id=worker_id,
        capability_id=capability_id,
        outcome=outcome,
        date_from=date_from,
        date_to=date_to,
        cursor=cursor,
        limit=limit,
    )

    # 富化 worker_name
    worker_ids = list({item.worker_id for item in items})
    worker_names: dict[str, str] = {}
    if worker_ids:
        result = await db.execute(
            select(Worker.id, Worker.name).where(Worker.id.in_(worker_ids))
        )
        worker_names = {row[0]: row[1] for row in result.all()}

    data = [
        CapabilityAuditResponse(
            id=item.id,
            project_id=item.project_id,
            worker_id=item.worker_id,
            capability_id=item.capability_id,
            authorization_request_id=item.authorization_request_id,
            command=item.command,
            exit_code=item.exit_code,
            duration_ms=item.duration_ms,
            outcome=item.outcome,
            actor_type=item.actor_type,
            actor_id=item.actor_id,
            created_at=item.created_at,
            worker_name=worker_names.get(item.worker_id),
        )
        for item in items
    ]

    return CapabilityAuditPage(
        items=data,
        next_cursor=next_cursor,
        total=total,
    )
