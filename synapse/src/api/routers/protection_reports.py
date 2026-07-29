"""ProtectionReport API 端点 — 保护报告的 REST 接口。

P10-B37: 议题 ⑥ API 层首次落地。

端点:
- POST   /projects/{pid}/protection-reports      创建保护报告
- GET    /projects/{pid}/protection-reports      分页列表
- GET    /protection-reports/{id}                单条详情
- POST   /protection-reports/{id}/run            触发执行
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.permissions import require_permission
from src.schemas.common import CursorPage
from src.schemas.protection import ProtectionReportCreate, ProtectionReportResponse
from src.services.protection_service import (
    create_report,
    get_report,
    list_reports,
    run_report,
)

from .helpers import get_project_or_404

router = APIRouter()


# ── 内部辅助 ──────────────────────────────────────────────────────────


def _to_response(record) -> ProtectionReportResponse:
    """ORM → Pydantic，手动处理 JSON 字段。"""
    response = ProtectionReportResponse.model_validate(record)
    if record.parameters_json:
        try:
            response.parameters = json.loads(record.parameters_json)
        except (json.JSONDecodeError, TypeError):
            response.parameters = None
    if record.result_json:
        try:
            response.result = json.loads(record.result_json)
        except (json.JSONDecodeError, TypeError):
            response.result = None
    return response


# ═══════════════════════════════════════════════════════════════════════
# POST /projects/{project_id}/protection-reports
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "/projects/{project_id}/protection-reports",
    response_model=ProtectionReportResponse,
    status_code=201,
)
async def create_protection_report(
    project_id: str,
    body: ProtectionReportCreate,
    actor: ActorInfo = Depends(require_permission("protection_report:create")),
    db: AsyncSession = Depends(get_db),
):
    """创建保护报告 — 手动触发检测。

    管理员或组长可以手动触发三种检测模式之一：
    - cross_project_access: 跨 Project 访问检测
    - sensitive_overlap: 敏感 Worker 重叠检测
    - capability_drift: Worker 能力漂移检测

    报告创建后状态为 pending，需调用 run 端点执行。
    """
    await get_project_or_404(db, project_id)

    report = await create_report(
        db,
        project_id=project_id,
        report_type=body.report_type,
        triggered_by="manual",
        parameters=body.parameters,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return _to_response(report)


# ═══════════════════════════════════════════════════════════════════════
# GET /projects/{project_id}/protection-reports
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/protection-reports",
    response_model=CursorPage[ProtectionReportResponse],
)
async def list_protection_reports(
    project_id: str,
    report_type: str | None = Query(
        None, pattern=r"^(cross_project_access|sensitive_overlap|capability_drift)$",
    ),
    status: str | None = Query(
        None, pattern=r"^(pending|running|completed|failed)$",
    ),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    actor: ActorInfo = Depends(require_permission("protection_report:read")),
    db: AsyncSession = Depends(get_db),
):
    """分页查询保护报告，按创建时间降序。

    支持按 report_type、status 筛选。
    """
    await get_project_or_404(db, project_id)

    items, next_cursor, total = await list_reports(
        db,
        project_id=project_id,
        report_type=report_type,
        status=status,
        cursor=cursor,
        limit=limit,
    )

    return CursorPage(
        items=[_to_response(r) for r in items],
        next_cursor=next_cursor,
        total=total,
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /protection-reports/{report_id}
# ═══════════════════════════════════════════════════════════════════════


async def _resolve_project_from_report(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from report_id in URL path parameters.

    Used by ``require_permission`` for report detail/run endpoints that don't
    have ``project_id`` in their URL path.
    """
    report_id = request.path_params["report_id"]
    report = await get_report(db, report_id)
    return report.project_id


@router.get(
    "/protection-reports/{report_id}",
    response_model=ProtectionReportResponse,
)
async def get_protection_report(
    report_id: str,
    actor: ActorInfo = Depends(
        require_permission(
            "protection_report:read",
            resolve_project_id=_resolve_project_from_report,
        )
    ),
    db: AsyncSession = Depends(get_db),
):
    """获取单个保护报告详情。

    权限：报告所属 Project 的 admin/lead，或超管。
    """
    report = await get_report(db, report_id)
    return _to_response(report)


# ═══════════════════════════════════════════════════════════════════════
# POST /protection-reports/{report_id}/run
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "/protection-reports/{report_id}/run",
    response_model=ProtectionReportResponse,
)
async def run_protection_report(
    report_id: str,
    actor: ActorInfo = Depends(
        require_permission(
            "protection_report:run",
            resolve_project_id=_resolve_project_from_report,
        )
    ),
    db: AsyncSession = Depends(get_db),
):
    """执行保护报告检测 — pending → running → completed/failed。

    权限：报告所属 Project 的 admin/lead，或超管。

    B36 骨架实现：执行基本状态转换。三个检测模式的实际分析逻辑在远期实现。
    """
    report = await get_report(db, report_id)

    updated = await run_report(
        db,
        report_id=report_id,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return _to_response(updated)
