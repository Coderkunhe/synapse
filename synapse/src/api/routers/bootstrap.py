"""Bootstrap API route — one-command Worker setup.

``GET /v1/bootstrap`` returns a self-contained setup script (format=sh)
or a JSON file manifest (format=json) that installs the Synapse Worker
Skill into the local project directory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import extract_bearer_token, hash_api_key, hash_project_key
from src.constants import WorkerStatus
from src.db import get_db
from src.exceptions import AuthenticationError, ForbiddenError, NotFoundError
from src.models.project import Project
from src.models.worker import Worker
from src.services.bootstrap_service import (
    build_bootstrap_json,
    build_bootstrap_sh,
)
from src.services.template_service import resolve_role

router = APIRouter()


@router.get("/bootstrap")
async def bootstrap(
    worker_id: str = Query(..., description="Worker ID"),
    project_id: str = Query(..., description="Project ID to bootstrap for"),
    client: str = Query(
        "auto",
        pattern=r"^(auto|claude|codex|cursor)$",
        description="Target AI client type",
    ),
    role: str | None = Query(
        None,
        pattern=r"^(orchestrator|builder|steward)$",
        description="Override role",
    ),
    fmt: str = Query(
        "sh",
        alias="format",
        pattern=r"^(sh|json)$",
        description="Output format: sh (shell script) or json (AI self-bootstrap)",
    ),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
):
    """Return a self-contained Worker bootstrap script or JSON manifest.

    **Scenario A — Terminal pipe (format=sh, default):**

    .. code-block:: bash

        curl -sS {api_url}/v1/bootstrap?worker_id=X&project_id=Y \\
          -H "Authorization: Bearer $KEY" | bash

    **Scenario B — AI self-bootstrap (format=json):**

    The AI agent (already running in the project directory) calls this
    endpoint, receives a JSON file manifest, and writes each file using
    its own Write tool. Then prompts the user to restart the session.
    """
    # ── Authentication (dual-path, same as protocol endpoint) ──
    token = await extract_bearer_token(request)
    if not token:
        raise AuthenticationError(
            "AUTH_MISSING_TOKEN", "Missing authentication token"
        )

    worker = None
    project = None

    # ① Try API key validation first
    key_hash = hash_api_key(token)
    result = await db.execute(
        select(Worker)
        .options(selectinload(Worker.team))
        .where(
            Worker.id == worker_id,
            Worker.api_key_hash == key_hash,
        )
    )
    worker = result.scalar_one_or_none()

    # ② API key failed → try project_key (P11-B9)
    if worker is None:
        proj_key_hash = hash_project_key(token)
        proj_result = await db.execute(
            select(Project).where(
                Project.project_key_hash == proj_key_hash,
            )
        )
        project_from_key = proj_result.scalar_one_or_none()

        if project_from_key is not None:
            worker = await db.get(Worker, worker_id)
            if worker is not None and worker.team_id == project_from_key.team_id:
                project = project_from_key
            else:
                raise AuthenticationError(
                    "AUTH_WORKER_NOT_IN_PROJECT_TEAM",
                    "Worker does not belong to the same team as the project key",
                )

    if worker is None:
        raise AuthenticationError(
            "AUTH_INVALID_API_KEY", "Invalid API key or project key"
        )

    # Accept PENDING or ACTIVE workers (new workers need bootstrap too)
    if worker.status not in (WorkerStatus.PENDING, WorkerStatus.ACTIVE):
        raise AuthenticationError(
            "AUTH_WORKER_NOT_ELIGIBLE",
            "Worker is not eligible for bootstrap",
        )

    # ── Resolve role ──
    resolved_role, _role_source = resolve_role(worker, role)

    # ── Load project (if not already loaded via project_key) ──
    if project is None:
        project = await db.get(Project, project_id)
        if project is None:
            raise NotFoundError("project", project_id)
        if project.team_id != worker.team_id:
            raise ForbiddenError(
                "FORBIDDEN_CROSS_TEAM",
                "Worker and project belong to different teams",
            )

    # ── Derive API base URL from request ──
    api_base_url = str(request.base_url).rstrip("/")

    # ── Build and return ──
    if fmt == "json":
        manifest = build_bootstrap_json(
            worker_id=worker_id,
            project_id=project_id,
            api_base_url=api_base_url,
            api_key=token,
            role=resolved_role,
            client=client if client != "auto" else "claude",
        )
        return manifest

    script = build_bootstrap_sh(
        worker_id=worker_id,
        project_id=project_id,
        api_base_url=api_base_url,
        api_key=token,
        role=resolved_role,
        client=client,
    )
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
    )
