"""Skill 服务 — CRUD + 事件记录。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import SkillStatus
from src.exceptions import NotFoundError
from src.models.skill import Skill
from src.services.event_store import event_store
from src.utils.id_gen import generate_id
from src.utils.json_utils import safe_dumps, safe_loads


async def create_skill(
    db: AsyncSession,
    *,
    team_id: str,
    name: str,
    version: str = "1.0.0",
    template_md: str,
    protocol_spec: dict | None = None,
    scan_rule_ids: list[str] | None = None,
    metadata: dict | None = None,
    actor_type: str,
    actor_id: str,
) -> Skill:
    """创建新的 Skill 定义。记录 ``skill.created`` 事件。"""
    skill = Skill(
        id=generate_id("skill"),
        team_id=team_id,
        name=name,
        version=version,
        status=SkillStatus.ACTIVE,
        template_md=template_md,
        protocol_spec=safe_dumps(protocol_spec),
        scan_rule_ids=safe_dumps(scan_rule_ids),
        metadata_=safe_dumps(metadata),
        create_user_id=actor_id,
    )
    db.add(skill)

    await event_store.record(
        db,
        event_type="skill.created",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="skill",
        target_id=skill.id,
        payload={"name": name, "version": version},
    )

    return skill


async def get_skill(db: AsyncSession, skill_id: str) -> Skill:
    """按 ID 获取 Skill，不存在则抛出 NotFoundError。"""
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise NotFoundError("skill", skill_id)
    return skill


async def update_skill(
    db: AsyncSession,
    skill_id: str,
    *,
    name: str | None = None,
    version: str | None = None,
    status: str | None = None,
    template_md: str | None = None,
    protocol_spec: dict | None = None,
    scan_rule_ids: list[str] | None = None,
    metadata: dict | None = None,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Skill:
    """更新 Skill 字段。仅非 None 字段会被修改。

    如有字段变更则记录 ``skill.updated`` 或 ``skill.deprecated`` 事件。
    """
    skill = await get_skill(db, skill_id)

    changed = False
    if name is not None:
        skill.name = name
        changed = True
    if version is not None:
        skill.version = version
        changed = True
    if status is not None:
        skill.status = status
        changed = True
    if template_md is not None:
        skill.template_md = template_md
        changed = True
    if protocol_spec is not None:
        skill.protocol_spec = safe_dumps(protocol_spec)
        changed = True
    if scan_rule_ids is not None:
        skill.scan_rule_ids = safe_dumps(scan_rule_ids)
        changed = True
    if metadata is not None:
        skill.metadata_ = safe_dumps(metadata)
        changed = True

    if changed:
        event_type = (
            "skill.deprecated" if status == SkillStatus.DEPRECATED
            else "skill.updated"
        )
        await event_store.record(
            db,
            event_type=event_type,
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="skill",
            target_id=skill.id,
            payload={"status": skill.status},
        )

    return skill


async def list_skills(
    db: AsyncSession,
    team_id: str,
    *,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Skill], str | None, int | None]:
    """团队的游标分页 Skill 列表，最新优先。

    可按 ``status`` 过滤。
    """
    conditions = [Skill.team_id == team_id]
    if status:
        conditions.append(Skill.status == status)
    if cursor:
        conditions.append(Skill.id < cursor)

    stmt = (
        select(Skill)
        .where(*conditions)
        .order_by(Skill.created_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_conditions = [Skill.team_id == team_id]
    if status:
        count_conditions.append(Skill.status == status)
    count_stmt = select(func.count(Skill.id)).where(*count_conditions)
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total


def skill_to_response(skill: Skill) -> dict:
    """将 Skill ORM 对象转换为响应字典，含 JSON 反序列化。"""
    return {
        "id": skill.id,
        "team_id": skill.team_id,
        "name": skill.name,
        "version": skill.version,
        "status": skill.status,
        "template_md": skill.template_md,
        "protocol_spec": safe_loads(skill.protocol_spec),
        "scan_rule_ids": safe_loads(skill.scan_rule_ids),
        "metadata": safe_loads(skill.metadata_),
        "is_disabled": skill.is_disabled,
        "create_user_id": skill.create_user_id,
        "last_update_user_id": skill.last_update_user_id,
        "remark": skill.remark,
        "version_no": skill.version_no,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }
