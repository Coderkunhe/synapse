"""Skill API routes — create, list, get, update."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import NotFoundError
from src.schemas.common import CursorPage
from src.schemas.skill import SkillCreate, SkillResponse, SkillUpdate
from src.services.skill_service import (
    create_skill as _create_skill,
    get_skill as _get_skill,
    list_skills as _list_skills,
    skill_to_response,
    update_skill as _update_skill,
)

from .helpers import get_team_or_404

router = APIRouter()


@router.post(
    "/teams/{team_id}/skills",
    response_model=SkillResponse,
    status_code=201,
)
async def create_skill(
    team_id: str,
    body: SkillCreate,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Skill definition for the team."""
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    skill = await _create_skill(
        db,
        team_id=team_id,
        name=body.name,
        version=body.version,
        template_md=body.template_md,
        protocol_spec=body.protocol_spec,
        scan_rule_ids=body.scan_rule_ids,
        metadata=body.metadata_,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()
    return SkillResponse.model_validate(skill_to_response(skill))


@router.get(
    "/teams/{team_id}/skills",
    response_model=CursorPage[SkillResponse],
)
async def list_skills(
    team_id: str,
    status: str | None = Query(None, pattern=r"^(active|deprecated)$"),
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """List skills for the team, newest first.

    Optionally filtered by ``status``.
    """
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    items, next_cursor, total = await _list_skills(
        db,
        team_id,
        status=status,
        cursor=cursor,
        limit=limit,
    )
    return CursorPage(
        items=[skill_to_response(s) for s in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get(
    "/skills/{skill_id}",
    response_model=SkillResponse,
)
async def get_skill(
    skill_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single Skill definition by ID."""
    skill = await _get_skill(db, skill_id)
    if skill.team_id != actor.team_id:
        raise NotFoundError("skill", skill_id)
    return SkillResponse.model_validate(skill_to_response(skill))


@router.patch(
    "/skills/{skill_id}",
    response_model=SkillResponse,
)
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Update a Skill definition — only provided fields are changed."""
    skill = await _get_skill(db, skill_id)
    if skill.team_id != actor.team_id:
        raise NotFoundError("skill", skill_id)

    updated = await _update_skill(
        db,
        skill_id,
        name=body.name,
        version=body.version,
        status=body.status,
        template_md=body.template_md,
        protocol_spec=body.protocol_spec,
        scan_rule_ids=body.scan_rule_ids,
        metadata=body.metadata_,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=skill.team_id,
    )
    await db.commit()
    return SkillResponse.model_validate(skill_to_response(updated))
