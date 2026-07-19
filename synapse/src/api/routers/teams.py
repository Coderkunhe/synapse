"""Team and Member API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor, require_role
from src.exceptions import NotFoundError
from src.schemas.common import CursorPage
from src.schemas.member import MemberCreate, MemberResponse
from src.schemas.team import TeamResponse, TeamUpdate
from src.services.team_service import (
    invite_member as _invite_member,
    list_members as _list_members,
    member_to_response,
    remove_member as _remove_member,
    update_team as _update_team,
)

from .helpers import get_team_or_404

router = APIRouter()


# ── Team ──────────────────────────────────────────────────────────

@router.get(
    "/teams/{team_id}",
    response_model=TeamResponse,
    responses={404: {"model": None}},
)
async def get_team(
    team_id: str = Path(...),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)
    return TeamResponse.model_validate(team)


@router.patch("/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str,
    body: TeamUpdate,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    team = await _update_team(
        db,
        team_id,
        name=body.name,
        description=body.description,
        avatar_url=body.avatar_url,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id_for_event=actor.team_id,
    )
    await db.commit()
    return TeamResponse.model_validate(team)


# ── Member ────────────────────────────────────────────────────────

@router.get(
    "/teams/{team_id}/members",
    response_model=CursorPage[MemberResponse],
)
async def list_members(
    team_id: str,
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    items, next_cursor, total = await _list_members(
        db, team_id, cursor=cursor, limit=limit
    )
    return CursorPage(
        items=[MemberResponse.model_validate(member_to_response(m)) for m in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.post(
    "/teams/{team_id}/members",
    response_model=MemberResponse,
    status_code=201,
)
async def invite_member(
    team_id: str,
    body: MemberCreate,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    member = await _invite_member(
        db,
        team_id=team_id,
        user_id=body.user_id,
        display_name=body.display_name,
        role=body.role,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()
    return MemberResponse.model_validate(member_to_response(member))


@router.delete(
    "/teams/{team_id}/members/{member_id}",
    status_code=204,
)
async def remove_member(
    team_id: str,
    member_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    await _remove_member(
        db,
        member_id,
        team_id=team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()
    return None
