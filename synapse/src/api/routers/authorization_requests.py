"""AuthorizationRequest API 端点 — 异步授权请求的 REST 接口。

P10-B22: 议题 3 授权管道 API 层首次落地。

端点:
- POST   /projects/{pid}/authorization-requests      创建授权请求
- GET    /projects/{pid}/authorization-requests      列出项目下请求
- PATCH  /authorization-requests/{id}/respond        审批（approve/deny）
- PATCH  /authorization-requests/{id}/heartbeat      心跳续期（Worker 调用）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, check_project_role, get_current_actor, require_project_role
from src.exceptions import ForbiddenError, NotFoundError
from src.models.authorization_request import AuthorizationRequest
from src.constants import ActorType
from src.schemas.authorization_request import (
    AuthorizationRequestCreate,
    AuthorizationRequestHeartbeat,
    AuthorizationRequestRespond,
    AuthorizationRequestResponse,
)
from src.services.authorization_service import (
    create_authorization_request,
    get_request,
    heartbeat as heartbeat_service,
    respond_to_request,
)

from .helpers import get_project_or_404

router = APIRouter()


# ── 查询辅助 ──────────────────────────────────────────────────────

# _get_request_and_verify_project 已移除（P10-B39: S-063）。
# 改用 check_project_role()（src/dependencies.py）——与 require_project_role
# 共享同一套 role 检查逻辑，消除手动复制导致的 drift 风险。


# ═══════════════════════════════════════════════════════════════════
# POST /projects/{project_id}/authorization-requests
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/projects/{project_id}/authorization-requests",
    response_model=AuthorizationRequestResponse,
    status_code=201,
)
async def create_auth_request(
    project_id: str,
    body: AuthorizationRequestCreate,
    actor: ActorInfo = Depends(require_project_role("admin", "lead")),
    db: AsyncSession = Depends(get_db),
):
    """创建授权请求。

    人类管理员/组长可以手动创建授权请求。
    系统创建的授权请求（Worker 403 触发）也通过此端点。
    """
    # 验证 body 中的 project_id 与 URL 一致
    if body.project_id and body.project_id != project_id:
        raise ForbiddenError(
            "PROJECT_ID_MISMATCH",
            f"Body project_id ({body.project_id}) does not match URL ({project_id})",
        )

    project = await get_project_or_404(db, project_id)

    record = await create_authorization_request(
        db,
        project_id=project_id,
        worker_id=body.worker_id or actor.actor_id,
        request_type=body.request_type,
        operation=body.operation,
        target_resource_type=body.target_resource_type,
        target_resource_id=body.target_resource_id,
        prompt_type=body.prompt_type,
        prompt_message=body.prompt_message,
        prompt_choices=body.prompt_choices,
        ttl_seconds=body.ttl_seconds,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return _to_response(record)


# ═══════════════════════════════════════════════════════════════════
# GET /projects/{project_id}/authorization-requests
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/authorization-requests",
    response_model=list[AuthorizationRequestResponse],
)
async def list_auth_requests(
    project_id: str,
    status: str = Query("pending", pattern=r"^(pending|approved|denied|expired|cancelled)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor: ActorInfo = Depends(require_project_role("admin", "lead")),
    db: AsyncSession = Depends(get_db),
):
    """列出项目下的授权请求，默认返回 pending 状态。

    支持分页（limit/offset）和状态筛选。
    """
    project = await get_project_or_404(db, project_id)

    result = await db.execute(
        select(AuthorizationRequest)
        .where(
            AuthorizationRequest.project_id == project_id,
            AuthorizationRequest.status == status,
        )
        .order_by(AuthorizationRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    records = result.scalars().all()

    return [_to_response(r) for r in records]


# ═══════════════════════════════════════════════════════════════════
# PATCH /authorization-requests/{request_id}/respond
# ═══════════════════════════════════════════════════════════════════


@router.patch(
    "/authorization-requests/{request_id}/respond",
    response_model=AuthorizationRequestResponse,
)
async def respond_to_auth_request(
    request_id: str,
    body: AuthorizationRequestRespond,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """响应授权请求 — 批准或拒绝。

    Actor 必须是被请求 Project 的 admin/lead。

    P10-B39 (S-063): 改用 check_project_role() 替代手动复刻的
    role 检查，与 require_project_role 共享同一套权限逻辑。
    """
    # 获取记录以确定 project_id，同时验证存在性
    record = await get_request(db, request_id)

    # 验证 actor 对所属 project 有 admin/lead 角色
    # （check_project_role 自动处理 super_admin 绕过）
    await check_project_role(db, record.project_id, actor, "admin", "lead")

    record = await respond_to_request(
        db,
        request_id=request_id,
        responder_worker_id=actor.actor_id,
        status=body.status,
        response_note=body.response_note,
        response_data=body.response_data,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return _to_response(record)


# ═══════════════════════════════════════════════════════════════════
# PATCH /authorization-requests/{request_id}/heartbeat
# ═══════════════════════════════════════════════════════════════════


@router.patch(
    "/authorization-requests/{request_id}/heartbeat",
    response_model=AuthorizationRequestResponse,
)
async def heartbeat_auth_request(
    request_id: str,
    body: AuthorizationRequestHeartbeat | None = None,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """心跳续期 — 保持授权请求存活。

    Worker 定期调用此端点以防止其 pending 请求过期。
    仅请求的拥有者（worker_id == actor.actor_id）可以发送心跳。

    P10-B39 (S-064): 新增 project 成员校验 — 已撤销权限的 Worker
    在请求过期前不可继续发心跳。api_auth 类型除外（Worker 申请
    首角色时尚未有 project role）。
    """
    record = await get_request(db, request_id)

    # 验证 actor 是该请求的拥有者
    if record.worker_id != actor.actor_id and not actor.is_super_admin:
        raise ForbiddenError(
            "FORBIDDEN_NOT_REQUEST_OWNER",
            f"Only the request owner (worker_id={record.worker_id}) can send heartbeat",
        )

    # S-064: 验证 actor 仍是 project 成员（已撤销权限不可续期）
    # api_auth 类型：Worker 申请首角色，尚无 project role → 跳过
    if record.request_type != "api_auth":
        await check_project_role(
            db, record.project_id, actor, "admin", "lead", "member",
        )

    updated = await heartbeat_service(db, request_id)
    await db.commit()

    return _to_response(updated)


# ═══════════════════════════════════════════════════════════════════
# GET /authorization-requests/{request_id}
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/authorization-requests/{request_id}",
    response_model=AuthorizationRequestResponse,
)
async def get_auth_request(
    request_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """获取单个授权请求 — Worker 轮询审批状态。

    P10-B31: S-065 — Worker 收到 202 后轮询此端点等待审批结果。

    权限规则：
    - 请求拥有者（Worker）可以查看自己的请求
    - 项目的 admin/lead 可以查看项目内请求
    - 超管可以查看所有请求
    """
    record = await get_request(db, request_id)

    # Owner check: Worker can see their own requests
    is_owner = record.worker_id == actor.actor_id
    if is_owner:
        return _to_response(record)

    # Admin check: project admin/lead can see requests in their project
    if actor.is_super_admin:
        return _to_response(record)

    if actor.actor_type != ActorType.WORKER:
        from src.services.project_role_service import get_project_role
        role = await get_project_role(db, record.project_id, actor.actor_id)
        if role in ("admin", "lead"):
            return _to_response(record)

    raise ForbiddenError(
        "FORBIDDEN_NOT_REQUEST_OWNER",
        "You do not have permission to view this authorization request",
    )


# ═══════════════════════════════════════════════════════════════════
# GET /workers/me/authorization-requests
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/me/authorization-requests",
    response_model=list[AuthorizationRequestResponse],
)
async def list_my_auth_requests(
    status: str = Query("pending", pattern=r"^(pending|approved|denied|expired|cancelled|all)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """列出当前 Worker 自己的授权请求 — 无需 project role。

    P10-B31 (S-065 补充): Worker 自查询端点，支持发现 pending 的
    api_auth 和 interactive_prompt 请求。Worker 启动时或定期 poll
    此端点即可发现所有待处理的授权/决策请求。

    权限: 任何已认证的 actor（Worker 或 Human）都可以查看自己的请求。
    """
    conditions = [AuthorizationRequest.worker_id == actor.actor_id]
    if status != "all":
        conditions.append(AuthorizationRequest.status == status)

    result = await db.execute(
        select(AuthorizationRequest)
        .where(*conditions)
        .order_by(AuthorizationRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    records = result.scalars().all()

    return [_to_response(r) for r in records]


# ═══════════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════════


def _to_response(record: AuthorizationRequest) -> AuthorizationRequestResponse:
    """将 ORM 对象转换为 API 响应 schema。

    使用 model_validate 自动从 ORM 属性提取字段（from_attributes=True）。
    prompt_choices_json 字符串 → prompt_choices list 手动转换。
    """
    import json

    # 使用 from_attributes 自动映射 ORM → Pydantic
    response = AuthorizationRequestResponse.model_validate(record)

    # 手动转换 prompt_choices_json → prompt_choices
    if record.prompt_choices_json:
        try:
            response.prompt_choices = json.loads(record.prompt_choices_json)
        except (json.JSONDecodeError, TypeError):
            response.prompt_choices = None
    else:
        response.prompt_choices = None

    # Map ORM attribute name to Pydantic field name
    # (model_validate can't auto-map response_data_json → response_data)
    response.response_data = record.response_data_json

    return response
