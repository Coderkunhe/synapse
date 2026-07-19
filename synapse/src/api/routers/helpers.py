"""Shared helpers for API route handlers."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import NotFoundError
from src.models.event import Event
from src.models.project import Project
from src.models.team import Team


def event_to_response(event: Event) -> dict:
    """Convert an Event ORM object to a JSON-safe dict."""
    return {
        "id": event.id,
        "team_id": event.team_id,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "payload": json.loads(event.payload) if isinstance(event.payload, str) else event.payload,
        "idempotency_key": event.idempotency_key,
        "create_user_id": event.create_user_id,
        "created_at": event.created_at,
    }


async def get_team_or_404(db: AsyncSession, team_id: str) -> Team:
    """Fetch a team by ID or raise NotFoundError."""
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFoundError("team", team_id)
    return team


async def get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    """Fetch a project by ID or raise NotFoundError."""
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)
    return project
