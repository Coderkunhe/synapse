"""FastAPI dependency injection: DB session, current actor, permission guards."""

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import decode_access_token, extract_bearer_token, verify_api_key
from src.config import settings
from src.constants import ActorType
from src.db import get_db
from src.exceptions import AuthenticationError, AuthorizationPendingError, ForbiddenError
from src.services.project_role_service import get_project_role


@dataclass(frozen=True)
class ActorInfo:
    """Unified actor representation — either a Member (human) or Worker (AI).

    P10-B7: actor_id is now always a worker_id (for humans, derived from
    member_id via derive_id).
    P10-B8: actor_type is "human" (was "member") — aligned with
    WorkerActorType.HUMAN per ADR-004.
    P10-B17: is_super_admin + user_id added — DB 宽列首用，超管绕过权限检查。
    """

    actor_type: ActorType
    actor_id: str    # worker_id (P10-B7: was member_id for humans)
    team_id: str
    role: str | None = None  # for humans (from Member.role)
    name: str | None = None  # worker name or display_name
    user_id: str | None = None  # P10-B17: stable user identity (JWT sub)
    is_super_admin: bool = False  # P10-B17: super-admin bypass flag


async def get_current_actor(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ActorInfo:
    """Unified auth dependency: extracts and validates JWT or API Key.

    Returns ActorInfo regardless of auth method. Endpoints don't need to
    know whether the caller is a human or worker — they check permissions
    via the role/actor_type fields.
    """
    # Try httpOnly cookie first (browser clients), then Authorization header
    token = request.cookies.get(settings.access_token_cookie_name) or await extract_bearer_token(request)
    if not token:
        raise AuthenticationError("AUTH_MISSING_TOKEN", "Missing authentication token")

    # Try API Key first (worker auth) — starts with configured prefix
    if token.startswith("sk-syn-"):
        worker_info = await verify_api_key(token, db)
        if worker_info:
            return ActorInfo(
                actor_type=ActorType.WORKER,
                actor_id=worker_info["actor_id"],
                team_id=worker_info["team_id"],
                name=worker_info.get("name"),
            )
        raise AuthenticationError("AUTH_INVALID_API_KEY", "Invalid API key")

    # Otherwise treat as JWT (actor auth — human via OAuth)
    payload = decode_access_token(token)
    return ActorInfo(
        actor_type=payload.get("actor_type", ActorType.HUMAN),
        actor_id=payload.get("actorId", payload.get("memberId", payload["sub"])),
        team_id=payload.get("teamId", payload.get("team_id", "")),
        role=payload.get("role"),
        user_id=payload.get("sub"),  # P10-B17: stable user identity
        is_super_admin=payload.get("is_super_admin", False),  # P10-B17: super-admin bypass
    )


def require_role(*roles: str):
    """Dependency factory: only allow actors with one of the given roles.

    P10-B17: super-admin actors bypass all role checks.

    Usage:
        @router.post("/tasks/{id}/assign")
        async def assign_task(actor: ActorInfo = Depends(require_role("admin", "lead"))):
            ...
    """
    async def guard(actor: ActorInfo = Depends(get_current_actor)) -> ActorInfo:
        if actor.actor_type == ActorType.WORKER:
            raise ForbiddenError("FORBIDDEN_WORKER_CANNOT_PERFORM_THIS_ACTION", "Worker cannot perform this action")
        # P10-B17: super-admin bypasses all role checks
        if actor.is_super_admin:
            return actor
        if actor.role not in roles:
            raise ForbiddenError("FORBIDDEN_INSUFFICIENT_ROLE", "Insufficient role permissions")
        return actor
    return guard


def require_super_admin():
    """Dependency factory: only allow super-admin actors.

    P10-B17: DB 宽列首用 — is_super_admin 标记的第一个消费者。

    Usage:
        @router.get("/admin/users")
        async def list_users(actor: ActorInfo = Depends(require_super_admin())):
            ...
    """
    async def guard(actor: ActorInfo = Depends(get_current_actor)) -> ActorInfo:
        if actor.actor_type == ActorType.WORKER:
            raise ForbiddenError("FORBIDDEN_WORKER_CANNOT_PERFORM_THIS_ACTION", "Worker cannot perform this action")
        if not actor.is_super_admin:
            raise ForbiddenError(
                "FORBIDDEN_SUPER_ADMIN_REQUIRED",
                "This action requires super-admin privileges",
            )
        return actor
    return guard


async def check_project_role(
    db: AsyncSession,
    project_id: str,
    actor: ActorInfo,
    *roles: str,
) -> None:
    """Verify that an actor has one of the required roles in a project.

    A standalone, reusable version of the core role-checking logic from
    ``require_project_role``.  Use this when ``project_id`` is not in the
    URL path (e.g. respond / heartbeat endpoints that look up the project
    from an authorization request record).

    Super-admin actors bypass all role checks (P10-B17).

    Raises:
        ForbiddenError: if the actor does not have the required role.

    Note:
        This is a **pure check** — it does NOT trigger the Worker
        authorization flow (P10-B31).  For endpoints where Workers may
        legitimately lack a role (i.e. most CRUD operations guarded by
        ``require_project_role``), use the ``require_project_role``
        dependency instead.
    """
    if actor.is_super_admin:
        return

    role = await get_project_role(db, project_id, actor.actor_id)

    if role is None:
        raise ForbiddenError(
            "FORBIDDEN_NOT_PROJECT_MEMBER",
            "You are not a member of this project",
        )
    if role not in roles:
        raise ForbiddenError(
            "FORBIDDEN_INSUFFICIENT_PROJECT_ROLE",
            f"This action requires project role: {', '.join(roles)}",
        )


def require_project_role(*roles: str, project_id_param: str = "project_id"):
    """Dependency factory: only allow actors with a specific role in a project.

    P10-B18: project_actor_roles 首次接线 — ADR-004 解析链路落地。
    P10-B31: S-065 Worker 403 拦截器 — Worker 无 project role 时自动创建
    api_auth AuthorizationRequest，返回 202 让 Worker 进入 poll 模式。

    Checks the ``project_actor_roles`` table for the actor's role in the
    project identified by the ``project_id_param`` path parameter.

    Super-admin actors bypass all role checks (P10-B17).
    Workers without a project role trigger the authorization flow (P10-B31).
    Humans without a project role receive a 403 ForbiddenError.

    Usage:
        @router.patch("/projects/{project_id}")
        async def update_project(
            project_id: str,
            actor: ActorInfo = Depends(require_project_role("admin")),
        ):
            ...

    The dependency extracts ``project_id`` from ``request.path_params``
    using the name given by ``project_id_param`` (default ``"project_id"``).
    """
    async def guard(
        request: Request,
        actor: ActorInfo = Depends(get_current_actor),
        db: AsyncSession = Depends(get_db),
    ) -> ActorInfo:
        project_id = request.path_params.get(project_id_param)
        if not project_id:
            raise RuntimeError(
                f"Path parameter '{project_id_param}' not found in route. "
                f"Ensure the route includes {{"
                + project_id_param
                + "}}."
            )

        try:
            await check_project_role(db, project_id, actor, *roles)
        except ForbiddenError:
            # ── Worker 403 拦截器 (P10-B31: S-065) ──
            if actor.actor_type == ActorType.WORKER:
                current_role = await get_project_role(
                    db, project_id, actor.actor_id,
                )
                await _trigger_authorization_flow(
                    db, request, project_id, actor, roles,
                    current_role=current_role,
                )
            raise

        return actor
    return guard


# ── P10-B31: Worker authorization flow helper ────────────────────────


def _infer_operation(request: Request) -> str:
    """Infer the operation name from the request method and path.

    Examples:
        POST /v1/projects/{pid}/tasks → "POST:/v1/projects/{pid}/tasks"
        PATCH /v1/projects/{pid}/tasks/{tid} → "PATCH:/v1/projects/{pid}/tasks/{tid}"
    """
    return f"{request.method}:{request.url.path}"


def _infer_resource_type(request: Request) -> str | None:
    """Infer the target resource type from the URL path.

    Matches known resource segments in the path and returns the type name.
    """
    path = request.url.path
    # Ordered by specificity — check longer path segments first
    resource_map = [
        ("authorization-requests", "authorization_request"),
        ("conversations", "conversation"),
        ("verifications", "verification"),
        ("workflows", "workflow"),
        ("batches", "batch"),
        ("tasks", "task"),
        ("projects", "project"),
        ("workers", "worker"),
        ("teams", "team"),
    ]
    for segment, resource_type in resource_map:
        if f"/{segment}" in path:
            return resource_type
    return None


def _infer_resource_id(request: Request) -> str | None:
    """Extract the most specific resource ID from path parameters.

    Tries common ID parameter names in order of specificity.
    """
    for param in ("task_id", "batch_id", "workflow_id", "verification_id",
                   "request_id", "conversation_id", "worker_id"):
        val = request.path_params.get(param)
        if val:
            return val
    # Fallback: project_id is the least specific
    return request.path_params.get("project_id")


async def _trigger_authorization_flow(
    db: AsyncSession,
    request: Request,
    project_id: str,
    actor: ActorInfo,
    required_roles: tuple[str, ...],
    current_role: str | None = None,
) -> None:
    """Auto-create an api_auth AuthorizationRequest for a Worker and
    raise AuthorizationPendingError (202).

    P10-B31: S-065 — 前半段授权闭环。Worker 遇权限不足时不直接 403，
    而是自动创建 api_auth 请求，由人类审批后自动授权并重放。
    """
    from src.services.authorization_service import create_authorization_request

    operation = _infer_operation(request)
    target_type = _infer_resource_type(request)
    target_id = _infer_resource_id(request)

    # Build a human-readable operation description
    role_gap = f" (current role: {current_role})" if current_role else ""
    detail_msg = (
        f"Worker '{actor.name or actor.actor_id}' attempted "
        f"{request.method} {request.url.path} "
        f"but lacks required role(s): {', '.join(required_roles)}{role_gap}"
    )

    auth_request = await create_authorization_request(
        db,
        project_id=project_id,
        worker_id=actor.actor_id,
        request_type="api_auth",
        operation=operation,
        target_resource_type=target_type,
        target_resource_id=target_id,
        prompt_message=detail_msg,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    raise AuthorizationPendingError(
        authorization_request_id=auth_request.id,
        details={
            "operation": operation,
            "target_resource_type": target_type,
            "target_resource_id": target_id,
            "required_roles": list(required_roles),
            "worker_id": actor.actor_id,
            "project_id": project_id,
        },
    )
