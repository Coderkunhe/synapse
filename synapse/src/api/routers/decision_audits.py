"""DecisionAudit API 端点 — 决策审计记录的只读查询。

P10-B37: 议题 ⑥ API 层首次落地。

端点:
- GET    /projects/{pid}/decision-audits      分页列表
- GET    /decision-audits/{id}                单条详情
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.permissions import require_permission
from src.schemas.common import CursorPage
from src.schemas.protection import DecisionAuditResponse
from src.services.decision_audit_service import get_decision, list_decisions

from .helpers import get_project_or_404

router = APIRouter()


# ── 内部辅助 ──────────────────────────────────────────────────────────


def _to_response(record) -> DecisionAuditResponse:
    """ORM → Pydantic，手动处理 context_json 字段。"""
    response = DecisionAuditResponse.model_validate(record)
    if record.context_json:
        try:
            response.context = json.loads(record.context_json)
        except (json.JSONDecodeError, TypeError):
            response.context = None
    return response


# ═══════════════════════════════════════════════════════════════════════
# GET /projects/{project_id}/decision-audits
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/decision-audits",
    response_model=CursorPage[DecisionAuditResponse],
)
async def list_project_decision_audits(
    project_id: str,
    worker_id: str | None = Query(None),
    decision_type: str | None = Query(
        None, pattern=r"^(approve|deny|expire|cancel|auto_grant)$",
    ),
    risk_level: str | None = Query(
        None, pattern=r"^(low|medium|high|critical)$",
    ),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    actor: ActorInfo = Depends(require_permission("decision_audit:read")),
    db: AsyncSession = Depends(get_db),
):
    """分页查询项目下的决策审计记录，按决策时间降序。

    支持按 worker_id、decision_type、risk_level 筛选。
    仅项目 admin/lead 可访问。
    """
    await get_project_or_404(db, project_id)

    items, next_cursor, total = await list_decisions(
        db,
        project_id=project_id,
        worker_id=worker_id,
        decision_type=decision_type,
        risk_level=risk_level,
        cursor=cursor,
        limit=limit,
    )

    return CursorPage(
        items=[_to_response(r) for r in items],
        next_cursor=next_cursor,
        total=total,
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /decision-audits/{decision_id}
# ═══════════════════════════════════════════════════════════════════════


async def _resolve_project_from_decision(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from decision_id in URL path parameters.

    Used by ``require_permission`` for the GET detail endpoint that doesn't
    have ``project_id`` in its URL path.
    """
    decision_id = request.path_params["decision_id"]
    decision = await get_decision(db, decision_id)
    return decision.project_id


@router.get(
    "/decision-audits/{decision_id}",
    response_model=DecisionAuditResponse,
)
async def get_decision_audit(
    decision_id: str,
    actor: ActorInfo = Depends(
        require_permission(
            "decision_audit:read",
            resolve_project_id=_resolve_project_from_decision,
        )
    ),
    db: AsyncSession = Depends(get_db),
):
    """获取单条决策审计记录。

    权限：记录所属 Project 的 admin/lead，或超管。
    """
    record = await get_decision(db, decision_id)
    return _to_response(record)
