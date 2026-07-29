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
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, check_project_role, get_current_actor
from src.permissions import require_permission
from src.exceptions import ForbiddenError, NotFoundError
from src.models.authorization_request import AuthorizationRequest
from src.constants import ActorType
from src.schemas.authorization_request import (
    AuthorizationRequestCreate,
    AuthorizationRequestHeartbeat,
    AuthorizationRequestReport,
    AuthorizationRequestRespond,
    AuthorizationRequestResponse,
)
from src.services.authorization_service import (
    create_authorization_request,
    find_pending_duplicate,
    get_request,
    heartbeat as heartbeat_service,
    report_execution,
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
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """创建授权请求。

    人类管理员/组长可以手动创建授权请求。
    系统创建的授权请求（Worker 403 触发）也通过此端点。
    Worker 可以通过 API key 为自己创建 capability_exec 请求（P11-B47）。
    """
    # 验证 body 中的 project_id 与 URL 一致
    if body.project_id and body.project_id != project_id:
        raise ForbiddenError(
            "PROJECT_ID_MISMATCH",
            f"Body project_id ({body.project_id}) does not match URL ({project_id})",
        )

    project = await get_project_or_404(db, project_id)

    # P11-B47: Worker 自请求 capability_exec → 旁路 role 检查
    # 其他请求类型（api_auth, interactive_prompt）→ 仍需 admin/lead
    is_self_capability = (
        body.request_type == "capability_exec"
        and body.worker_id
        and body.worker_id == actor.actor_id
    )
    if not is_self_capability:
        await check_project_role(db, project_id, actor, "admin", "lead")

    # P11-B50 + P100-B99: capability_exec 去重
    # - pending: 已有等待审批的请求 → 返回已有（防重复创建）
    # - approved + outcome=null: 孤儿批准（synapse-exec 超时退出后用户在 Web UI 批准）
    #   → 返回已有，synapse-exec 看到 approved 直接执行（打破"批了又回来"循环）
    if body.request_type == "capability_exec" and body.capability_id:
        existing = await find_pending_duplicate(
            db, body.worker_id or actor.actor_id, body.capability_id
        )
        if existing:
            data = await _to_response(existing, db)
            return JSONResponse(content=data.model_dump(mode="json"), status_code=200)

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
        capability_id=body.capability_id,
        ttl_seconds=body.ttl_seconds,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return await _to_response(record, db)


# ═══════════════════════════════════════════════════════════════════
# GET /projects/{project_id}/authorization-requests
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/authorization-requests",
    response_model=list[AuthorizationRequestResponse],
)
async def list_auth_requests(
    project_id: str,
    status: str = Query("pending", pattern=r"^(pending|approved|denied|expired|cancelled|all)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    actor: ActorInfo = Depends(require_permission("authorization:read")),
    db: AsyncSession = Depends(get_db),
):
    """列出项目下的授权请求，默认返回 pending 状态。

    支持分页（limit/offset）和状态筛选。
    status=all 返回所有非 pending 状态（P11-B44: 审批历史）。
    """
    project = await get_project_or_404(db, project_id)

    conditions = [AuthorizationRequest.project_id == project_id]
    if status != "all":
        conditions.append(AuthorizationRequest.status == status)
    else:
        # history tab: exclude pending
        conditions.append(AuthorizationRequest.status != "pending")

    result = await db.execute(
        select(AuthorizationRequest)
        .where(*conditions)
        .order_by(AuthorizationRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    records = result.scalars().all()

    return [await _to_response(r, db) for r in records]


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

    # P11-B81 PFL-047 L3: API 硬门禁 — Worker 不可审批授权请求
    # 审批人是 Human（且仅限 Human），任何 Worker（含 Orchestrator）尝试审批直接 403
    if actor.actor_type == ActorType.WORKER:
        raise ForbiddenError(
            "WORKER_CANNOT_APPROVE",
            "Only humans can approve or deny authorization requests. "
            "Workers (including Orchestrators) are not authorized to respond to authorization requests. "
            "Please open the Synapse Web UI to approve this request.",
        )

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

    return await _to_response(record, db)


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

    return await _to_response(updated, db)


# ═══════════════════════════════════════════════════════════════════
# POST /authorization-requests/{request_id}/report
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/authorization-requests/{request_id}/report",
    response_model=AuthorizationRequestResponse,
)
async def report_execution_result(
    request_id: str,
    body: AuthorizationRequestReport,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """上报 capability 执行结果 — P11-B46。

    Worker 在 capability 批准并执行后调用此端点。
    只有请求的拥有者（worker_id == actor.actor_id）可以上报。
    """
    record = await report_execution(
        db,
        request_id=request_id,
        worker_id=actor.actor_id,
        outcome=body.outcome,
        exit_code=body.exit_code,
        duration_ms=body.duration_ms,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return await _to_response(record, db)


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
        return await _to_response(record, db)

    # Admin check: project admin/lead can see requests in their project
    if actor.is_super_admin:
        return await _to_response(record, db)

    if actor.actor_type != ActorType.WORKER:
        from src.services.project_role_service import get_project_role
        role = await get_project_role(db, record.project_id, actor.actor_id)
        if role in ("admin", "lead"):
            return await _to_response(record, db)

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

    return [await _to_response(r, db) for r in records]


# ═══════════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════════


async def _to_response(record: AuthorizationRequest, db: AsyncSession) -> AuthorizationRequestResponse:
    """将 ORM 对象转换为 API 响应 schema，并富化 worker name。

    使用 model_validate 自动从 ORM 属性提取字段（from_attributes=True）。
    prompt_choices_json 字符串 → prompt_choices list 手动转换。
    worker_name / responded_by_worker_name 从 Worker 表 lookup 填充。
    """
    import json

    from src.models.worker import Worker

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

    # ── 富化: resolve worker names ──
    worker_result = await db.execute(
        select(Worker.name).where(Worker.id == record.worker_id)
    )
    response.worker_name = worker_result.scalar_one_or_none()

    if record.responded_by_worker_id:
        responder_result = await db.execute(
            select(Worker.name).where(Worker.id == record.responded_by_worker_id)
        )
        response.responded_by_worker_name = responder_result.scalar_one_or_none()

    # ── 富化: resolve target resource name（P11-B44）──
    if record.target_resource_type and record.target_resource_id:
        if record.target_resource_type == "task":
            from src.models.task import Task
            task_result = await db.execute(
                select(Task.title).where(Task.id == record.target_resource_id)
            )
            response.target_resource_name = task_result.scalar_one_or_none()

    return response
