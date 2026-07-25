"""Unified permission engine — declaration table + role hierarchy + guard dependency.

P11-B8: 地基 — centralized permission registry replacing ad-hoc role checks
scattered across 10+ endpoints.  Provides ``require_permission("task:claim")``
as a single-point-of-truth guard dependency.

Design principles:
- **Declaration over imperative**: permissions live in PERMISSION_MAP, not in
  individual endpoint function signatures.
- **Role hierarchy**: ``admin`` inherits all operation roles without
  needing separate project_actor_roles entries.
- **Backend-complete**: steward role is defined and functional server-side even
  though the frontend hides it (P11-B8 decision: dual-role UI, triple-role backend).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import ForbiddenError
from src.services.project_role_service import get_project_role


# ═══════════════════════════════════════════════════════════════════════
# Role Hierarchy
# ═══════════════════════════════════════════════════════════════════════

ROLE_HIERARCHY: dict[str, set[str]] = {
    # admin inherits all Synapse operation roles.
    # When checking e.g. "task:claim" (requires builder), an admin
    # passes because they inherit the builder role.
    "admin": {"orchestrator", "builder", "steward"},
    # orchestrator, builder, steward — no inheritance (leaf roles)
}


# ═══════════════════════════════════════════════════════════════════════
# Permission Registry
# ═══════════════════════════════════════════════════════════════════════

PERMISSION_MAP: dict[str, set[str]] = {
    # ── Task operations — orchestrator domain ──
    "task:create":  {"super_admin", "admin", "orchestrator"},
    "task:ready":   {"super_admin", "admin", "orchestrator"},
    "task:update":  {"super_admin", "admin", "orchestrator"},
    "task:assign":  {"super_admin", "admin", "orchestrator"},
    "task:cancel":    {"super_admin", "admin", "orchestrator"},
    "task:terminate": {"super_admin", "admin", "orchestrator"},
    "task:verify":    {"super_admin", "admin", "orchestrator"},

    # ── Task operations — builder domain ──
    "task:claim":   {"super_admin", "admin", "builder"},
    "task:submit":  {"super_admin", "admin", "builder"},
    "task:start":   {"super_admin", "admin", "builder"},

    # ── Task operations — steward domain (backend-supported, frontend-hidden) ──
    "task:review":  {"super_admin", "admin", "steward"},

    # ── Read / comment — any project member ──
    "task:read":    {"super_admin", "admin", "orchestrator", "builder", "steward"},
    "task:comment": {"super_admin", "admin", "orchestrator", "builder", "steward"},

    # ── Project management ──
    "project:manage": {"super_admin", "admin"},
    "project:read":   {"super_admin", "admin", "orchestrator", "builder", "steward"},
}


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _expand_roles(roles: set[str]) -> set[str]:
    """Expand a set of roles through ROLE_HIERARCHY.

    ``admin`` → ``{admin, orchestrator, builder, steward}``.
    Leaf roles (orchestrator, builder, steward) remain unchanged.
    """
    result = set(roles)
    for role in roles:
        inherited = ROLE_HIERARCHY.get(role)
        if inherited:
            result.update(inherited)
    return result


def _resolve_project_id(request: Request, project_id_param: str) -> str:
    """Extract project_id from request path parameters.

    Raises RuntimeError if the parameter is missing (indicates a
    misconfigured route — the endpoint doesn't declare project_id in its path).
    """
    project_id = request.path_params.get(project_id_param)
    if not project_id:
        raise RuntimeError(
            f"Path parameter '{project_id_param}' not found in route. "
            f"Add {{{project_id_param}}} to the route path or pass a custom "
            f"project_id_param to require_permission()."
        )
    return project_id


# ═══════════════════════════════════════════════════════════════════════
# Guard Dependency
# ═══════════════════════════════════════════════════════════════════════

def require_permission(
    action: str,
    *,
    project_id_param: str = "project_id",
    resolve_project_id: Callable | None = None,
):
    """Dependency factory: require a specific permission for the current actor.

    Replaces ad-hoc ``require_role("admin", "lead")`` and
    ``require_project_role("admin", "orchestrator")`` with a centralized
    permission check::

        @router.post("/projects/{project_id}/tasks")
        async def create_task(
            project_id: str,
            actor: ActorInfo = Depends(require_permission("task:create")),
        ):
            ...

    **How it works**:

    1. ``super_admin`` — bypass all checks (platform-level override).
    2. Look up actor's project role from ``project_actor_roles``.
    3. Expand role through ``ROLE_HIERARCHY``.
    4. Check if the expanded role intersects with the allowed roles for
       the action (from ``PERMISSION_MAP``).
    5. Worker without permission → triggers the authorization flow (202).
       Human without permission → 403 ForbiddenError.

    Args:
        action: Permission key from ``PERMISSION_MAP`` (e.g. ``"task:claim"``).
        project_id_param: Name of the URL path parameter containing the
            project ID. Default ``"project_id"``. Override for routes that
            use a different parameter name.
        resolve_project_id: Optional async callable ``(request, db) -> str``
            that resolves the project ID from the request. Use for endpoints
            that don't have ``project_id`` in their URL path (e.g. task_id-based
            routes that need to look up the task first). When provided, takes
            precedence over ``project_id_param``.
    """
    allowed_roles = PERMISSION_MAP.get(action)
    if allowed_roles is None:
        raise RuntimeError(
            f"Unknown permission action: '{action}'. "
            f"Registered actions: {', '.join(sorted(PERMISSION_MAP))}"
        )

    expanded = _expand_roles(allowed_roles)

    async def guard(
        request: Request,
        actor: ActorInfo = Depends(get_current_actor),
        db: AsyncSession = Depends(get_db),
    ) -> ActorInfo:
        # ① super_admin bypasses all permission checks
        if "super_admin" in expanded and actor.is_super_admin:
            return actor

        # Resolve project_id — use custom resolver if provided, else extract from path
        if resolve_project_id is not None:
            project_id = await resolve_project_id(request, db)
        else:
            project_id = _resolve_project_id(request, project_id_param)

        role = await get_project_role(db, project_id, actor.actor_id)

        # ② Check if actor's project role (after hierarchy expansion) is allowed
        if role and role in expanded:
            return actor

        # ③ Worker without permission → trigger authorization flow (202)
        if actor.actor_type == ActorType.WORKER:
            # Import inline to avoid circular dependency at module level.
            # _trigger_authorization_flow lives in dependencies.py alongside
            # the existing require_project_role guard — same pattern.
            from src.dependencies import _trigger_authorization_flow

            await _trigger_authorization_flow(
                db, request, project_id, actor,
                required_roles=tuple(expanded),
                current_role=role,
            )
            # _trigger_authorization_flow always raises AuthorizationPendingError
            # so we never reach this point. If the function returns (should not
            # happen), fall through to the ForbiddenError below.

        raise ForbiddenError(
            "FORBIDDEN_INSUFFICIENT_PERMISSION",
            f"Permission '{action}' requires one of: {', '.join(sorted(expanded))}. "
            f"Your project role: {role or '(none)'}.",
        )

    return guard
