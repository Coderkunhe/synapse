"""Template rendering service — {{VAR}} substitution + protocol assembly.

Variable resolution from four sources:
- Config (api_url, heartbeat_interval)
- Worker record (worker_id, role from metadata)
- Worker's Team (team_name via relationship)
- Project record (name, description, git_repo_url + metadata_ JSON)
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.worker import Worker
from src.models.project import Project
from src.utils.json_utils import safe_loads

from src.constants import ProjectRole

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "templates"

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")

# Workflow 职能角色 — 用于模板渲染的 role resolution。
# 包含有对应 role-*.md 模板的角色（orchestrator/builder/steward）。
# admin/lead/member 是 Project 管理权限，无对应模板。
# P10-B24: 值从 constants.ProjectRole 枚举派生。
# P11-B2: Steward 加入 VALID_ROLES（模板已完备，服务端暴露）。
VALID_ROLES: frozenset[str] = frozenset({
    ProjectRole.ORCHESTRATOR,
    ProjectRole.BUILDER,
    ProjectRole.STEWARD,
})


# ── Core render ────────────────────────────────────────────────────


def render(template_str: str, variables: dict[str, str | None]) -> tuple[str, list[str]]:
    """Replace ``{{VARIABLE}}`` placeholders with values.

    Returns:
        (rendered_str, unfilled_list) — unfilled_list contains variable names
        that were present in the template but missing or None in *variables*.
    """

    unfilled: list[str] = []

    def _replacer(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in variables:
            unfilled.append(name)
            return m.group(0)
        value = variables[name]
        if value is None:
            unfilled.append(name)
            return m.group(0)
        return str(value)

    result = _VAR_RE.sub(_replacer, template_str)
    return result, unfilled


# ── Template loading ────────────────────────────────────────────────


def load_template(name: str) -> str:
    """Read a template file from ``docs/templates/``.

    Raises:
        FileNotFoundError: if the template does not exist.
    """
    path = TEMPLATES_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Template not found: {name}")
    return path.read_text(encoding="utf-8")


# ── Variable resolution ────────────────────────────────────────────


async def resolve_variables(
    worker: Worker,
    project: Project,
    role: str,
    *,
    api_base_url: str = "http://localhost:8000",
    heartbeat_interval: int = 60,
) -> dict[str, str | None]:
    """Gather all template variables from DB records and config.

    Does **not** include ``SYNAPSE_API_KEY`` — that is a secret returned
    only once at Worker creation time.
    """

    worker_meta: dict = safe_loads(worker.metadata_) or {}
    project_meta: dict = safe_loads(project.metadata_) or {}

    # ── Conventions sub-object (P11-B5 frontend writes here) ──
    conventions: dict = project_meta.get("conventions", {}) or {}
    if not isinstance(conventions, dict):
        conventions = {}

    # ── Team name via relationship ──
    team_name: str | None = None
    team = getattr(worker, "team", None)
    if team is not None:
        team_name = getattr(team, "name", None)

    return {
        # Config-sourced
        "SYNAPSE_API_URL": api_base_url.rstrip("/"),
        "SYNAPSE_HEARTBEAT_INTERVAL": str(heartbeat_interval),
        # Worker-sourced
        "SYNAPSE_WORKER_ID": worker.id,
        "YOUR_ROLE": role,
        # Team-sourced
        "TEAM_NAME": team_name or "Unknown Team",
        # Project direct fields
        "PROJECT_NAME": project.name,
        # PROJECT_DESCRIPTION: project.description > conventions.projectDescription > ""
        "PROJECT_DESCRIPTION": (
            project.description
            or str(conventions.get("projectDescription", ""))
            or ""
        ),
        "GIT_REPO_URL": project.git_repo_url or "",
        "SYNAPSE_PROJECT_ID": project.id,
        # Project metadata JSON — tech stack & conventions
        # Priority: conventions.* (camelCase, from P11-B5 frontend) > old flat keys (snake_case, backward compat)
        "FRONTEND_STACK": str(conventions.get("frontendStack") or project_meta.get("frontend_stack", "")),
        "FRONTEND_NOTES": project_meta.get("frontend_notes", ""),
        "BACKEND_STACK": str(conventions.get("backendStack") or project_meta.get("backend_stack", "")),
        "BACKEND_NOTES": project_meta.get("backend_notes", ""),
        "DATABASE": str(conventions.get("database") or project_meta.get("database", "")),
        "DATABASE_NOTES": project_meta.get("database_notes", ""),
        "DEPLOYMENT": str(conventions.get("deployment") or project_meta.get("deployment", "")),
        "DEPLOYMENT_NOTES": project_meta.get("deployment_notes", ""),
        "CURRENT_PHASE": project_meta.get("current_phase", ""),
        "ACTIVE_BATCH": project_meta.get("active_batch", ""),
        "CURRENT_PRIORITY": project_meta.get("current_priority", ""),
        # ADMIN_NAME: conventions.adminName > old admin_name > ""
        "ADMIN_NAME": str(conventions.get("adminName") or project_meta.get("admin_name", "")),
        "ORCHESTRATOR_WORKER_ID": project_meta.get("orchestrator_worker_id", ""),
        "BUILDER_WORKER_ID": project_meta.get("builder_worker_id", ""),
        "STEWARD_WORKER_ID": project_meta.get("steward_worker_id", ""),
        "DOCS_URL": project.api_docs_url or project_meta.get("docs_url", ""),
        "CI_URL": project_meta.get("ci_url", ""),
        # PROJECT_CONVENTIONS: conventions.constraints > old project_conventions > ""
        "PROJECT_CONVENTIONS": str(conventions.get("constraints") or project_meta.get("project_conventions", "")),
        # Task-specific vars (TASK_ID, TASK_TITLE, …) — not resolvable
        # at project level; left for the caller to supply if needed.
    }


# ── Protocol assembly ───────────────────────────────────────────────


async def render_protocol(
    worker: Worker,
    project: Project,
    role: str,
    *,
    api_base_url: str = "http://localhost:8000",
    role_source: str = "worker_metadata",
) -> dict:
    """Render all four protocol templates and return a result dict.

    Keys: ``project_context``, ``collaboration_norms``, ``role_instructions``,
    ``env_template``, ``role_source``, ``unfilled_variables``.
    """

    variables = await resolve_variables(
        worker, project, role,
        api_base_url=api_base_url,
    )

    all_unfilled: list[str] = []

    # ── _project.md ──
    project_tpl = load_template("_project.md")
    project_rendered, unfilled = render(project_tpl, variables)
    all_unfilled.extend(unfilled)

    # ── _protocol.md (L1 platform protocol, replaces _common.md) ──
    protocol_tpl = load_template("_protocol.md")
    protocol_rendered, unfilled = render(protocol_tpl, variables)
    all_unfilled.extend(unfilled)

    # ── role-{role}.md ──
    role_filename = f"role-{role}.md"
    if not (TEMPLATES_DIR / role_filename).is_file():
        raise FileNotFoundError(f"Role template not found: {role_filename}")
    role_tpl = load_template(role_filename)
    role_rendered, unfilled = render(role_tpl, variables)
    all_unfilled.extend(unfilled)

    # ── _env.md ──
    env_tpl = load_template("_env.md")
    env_rendered, unfilled = render(env_tpl, variables)
    all_unfilled.extend(unfilled)

    return {
        "project_context": project_rendered,
        "collaboration_norms": protocol_rendered,
        "role_instructions": role_rendered,
        "env_template": env_rendered,
        "role_source": role_source,
        "unfilled_variables": sorted(set(all_unfilled)),
    }


# ── Role resolution helper ──────────────────────────────────────────


def resolve_role(worker: Worker, query_param_role: str | None = None) -> tuple[str, str]:
    """Determine worker role and its source.

    Resolution order: query param > worker metadata > default builder.

    Returns:
        (role, source) where source is one of:
        - ``"query_param"`` — role was explicitly passed as query parameter
        - ``"worker_metadata"`` — role from worker's metadata JSON
        - ``"default_fallback"`` — role defaulted to "builder" (G5: may indicate config error)
    """
    if query_param_role and query_param_role in VALID_ROLES:
        return query_param_role, "query_param"
    worker_meta: dict = safe_loads(worker.metadata_) or {}
    role = worker_meta.get("role")
    if role and role in VALID_ROLES:
        return str(role), "worker_metadata"
    return "builder", "default_fallback"
