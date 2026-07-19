"""决策审计 Service — 不可变审计记录写入 + 查询。

P10-B36: 议题 ⑥ Service 层 — DecisionAudit 接入。

每条授权决策（批准/拒绝/过期/取消/自动授权）记录一条不可变审计。
为远期信任分（trust score）提供数据基础。

决策审计不继承 AuditMixin，与 Event 模型对齐 — 只追加、不更新、不软删除。

调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import EventType
from src.exceptions import NotFoundError
from src.models.decision_audit import DecisionAudit
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ── 查询辅助 ──────────────────────────────────────────────────────


async def get_decision(
    db: AsyncSession,
    decision_id: str,
) -> DecisionAudit:
    """按 ID 获取决策审计记录，不存在则 raise NotFoundError。"""
    result = await db.execute(
        select(DecisionAudit).where(DecisionAudit.id == decision_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("DecisionAudit", decision_id)
    return record


async def list_decisions(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    worker_id: str | None = None,
    decision_type: str | None = None,
    risk_level: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[DecisionAudit], str | None, int | None]:
    """分页查询决策审计记录，按决策时间降序。

    支持按 project_id、worker_id、decision_type、risk_level 筛选。
    返回 (items, next_cursor, total)。
    """
    conditions: list = []
    if project_id:
        conditions.append(DecisionAudit.project_id == project_id)
    if worker_id:
        conditions.append(DecisionAudit.worker_id == worker_id)
    if decision_type:
        conditions.append(DecisionAudit.decision_type == decision_type)
    if risk_level:
        conditions.append(DecisionAudit.risk_level == risk_level)
    if cursor:
        conditions.append(DecisionAudit.id < cursor)

    stmt = (
        select(DecisionAudit)
        .where(*conditions)
        .order_by(DecisionAudit.created_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = (
        select(func.count(DecisionAudit.id)).where(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total


# ── 写入 ──────────────────────────────────────────────────────────


async def record_decision(
    db: AsyncSession,
    *,
    authorization_request_id: str | None,
    decision_type: str,
    actor_type: str,
    actor_id: str,
    project_id: str,
    worker_id: str,
    risk_level: str = "low",
    reason: str | None = None,
    context: dict | None = None,
    # 事件元数据
    team_id: str,
) -> DecisionAudit:
    """记录不可变审计条目。

    在每次授权决策（approve/deny/expire/cancel/auto_grant）时调用。
    同时记录 event_store 事件 DECISION_AUDIT_RECORDED。

    Args:
        authorization_request_id: 关联的授权请求 ID（系统自动决策可为 None）
        decision_type: approve | deny | expire | cancel | auto_grant
        actor_type: worker | human | system
        actor_id: 决策者 ID
        project_id: 所属 Project
        worker_id: 被决策的 Worker
        risk_level: low | medium | high | critical — 决策时的风险评估
        reason: 人类可读的决策理由
        context: 决策上下文（熔断状态、保护报告引用等）
        team_id: 事件元数据
    """
    audit = DecisionAudit(
        id=generate_id("decision_audit"),
        authorization_request_id=authorization_request_id,
        decision_type=decision_type,
        actor_type=actor_type,
        actor_id=actor_id,
        project_id=project_id,
        worker_id=worker_id,
        risk_level=risk_level,
        reason=reason,
        context_json=json.dumps(context) if context else None,
    )
    db.add(audit)
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.DECISION_AUDIT_RECORDED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="decision_audit",
        target_id=audit.id,
        payload={
            "decision_id": audit.id,
            "authorization_request_id": authorization_request_id,
            "decision_type": decision_type,
            "project_id": project_id,
            "worker_id": worker_id,
            "risk_level": risk_level,
        },
    )

    return audit
