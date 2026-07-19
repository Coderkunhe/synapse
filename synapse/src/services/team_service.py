"""Team 服务 — Team + Member CRUD + 事件记录。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import ConflictError, NotFoundError
from src.models.member import Member
from src.models.team import Team
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ── Team ──────────────────────────────────────────────────────────

async def get_team(db: AsyncSession, team_id: str) -> Team:
    """按 ID 获取团队，不存在则抛出 NotFoundError。"""
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFoundError("team", team_id)
    return team


async def update_team(
    db: AsyncSession,
    team_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    avatar_url: str | None = None,
    actor_type: str,
    actor_id: str,
    team_id_for_event: str,
) -> Team:
    """更新团队字段。仅非 None 字段会被修改。

    如有字段变更则记录 ``team.updated`` 事件。
    """
    team = await get_team(db, team_id)

    changed = False
    if name is not None:
        team.name = name
        changed = True
    if description is not None:
        team.description = description
        changed = True
    if avatar_url is not None:
        team.avatar_url = avatar_url
        changed = True

    if changed:
        await event_store.record(
            db,
            event_type="team.updated",
            team_id=team_id_for_event,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="team",
            target_id=team.id,
            payload={"status": "active"},
        )

    return team


# ── Member ────────────────────────────────────────────────────────

async def list_members(
    db: AsyncSession,
    team_id: str,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Member], str | None, int | None]:
    """游标分页列出团队成员。"""
    conditions = [Member.team_id == team_id]
    if cursor:
        conditions.append(Member.id > cursor)

    stmt = (
        select(Member)
        .where(*conditions)
        .order_by(Member.id)
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = list(rows[:limit])
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = select(func.count(Member.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total


async def invite_member(
    db: AsyncSession,
    *,
    team_id: str,
    user_id: str,
    display_name: str,
    role: str,
    actor_type: str,
    actor_id: str,
) -> Member:
    """邀请成员加入团队。检查团队内 user_id 重复。

    记录 ``member.invited`` 事件。
    """
    # 重复检查
    existing = await db.execute(
        select(Member).where(
            Member.team_id == team_id,
            Member.user_id == user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(
            "MEMBER_ALREADY_EXISTS",
            f"User {user_id} is already a member of team {team_id}",
        )

    member = Member(
        id=generate_id("member"),
        team_id=team_id,
        user_id=user_id,
        display_name=display_name,
        role=role,
        create_user_id=actor_id,
    )
    db.add(member)

    await event_store.record(
        db,
        event_type="member.invited",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="member",
        target_id=member.id,
        payload={"user_id": user_id, "role": role},
    )

    return member


async def remove_member(
    db: AsyncSession,
    member_id: str,
    *,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> None:
    """从团队移除成员。校验成员存在且属于该团队。

    记录 ``member.removed`` 事件。
    """
    member = await db.get(Member, member_id)
    if member is None or member.team_id != team_id:
        raise NotFoundError("member", member_id)

    await db.delete(member)

    await event_store.record(
        db,
        event_type="member.removed",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="member",
        target_id=member_id,
        payload={"user_id": member.user_id},
    )


def member_to_response(member: Member) -> dict:
    """将 Member ORM 对象转换为响应字典。"""
    return {
        "id": member.id,
        "team_id": member.team_id,
        "user_id": member.user_id,
        "display_name": member.display_name,
        "role": member.role,
        "joined_at": member.joined_at,
        "last_active_at": member.last_active_at,
        "is_disabled": member.is_disabled,
        "create_user_id": member.create_user_id,
        "last_update_user_id": member.last_update_user_id,
        "remark": member.remark,
        "version_no": member.version_no,
        "created_at": member.created_at,
        "updated_at": member.updated_at,
    }
