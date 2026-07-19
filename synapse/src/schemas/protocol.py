"""Protocol schema — worker protocol delivery API response."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProtocolResponse(BaseModel):
    """Rendered collaboration protocol for a worker.

    Returned by ``GET /workers/{worker_id}/protocol``.
    The four content fields are fully-rendered markdown with
    ``{{VARIABLE}}`` placeholders replaced by live DB values.
    ``unfilled_variables`` lists any variables that could not be resolved.
    """

    project_context: str = Field(
        ...,
        description="Rendered _project.md — tech stack, team, conventions",
    )
    collaboration_norms: str = Field(
        ...,
        description="Rendered _common.md — collaboration discipline for all workers",
    )
    role_instructions: str = Field(
        ...,
        description="Rendered role-{role}.md — role-specific responsibilities and workflow",
    )
    env_template: str = Field(
        ...,
        description="Rendered _env.md — environment variable configuration template",
    )
    unfilled_variables: list[str] = Field(
        default_factory=list,
        description="Variable names present in templates but unresolvable (e.g. TASK_*)",
    )
    role_source: str = Field(
        ...,
        description="Where the role was resolved from: query_param, worker_metadata, or default_fallback",
    )
