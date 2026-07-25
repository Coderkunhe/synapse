"""Capability 审计 Service — 不可变执行审计记录写入 + 查询。

P11-B57 (GAP-8): 每次 capability 执行完成后写一条不可变审计。
对齐 DecisionAudit 模式：只追加、不更新、不软删除。

审计写入与 report_execution 解耦 — 写入失败不阻断执行结果上报。
调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.capability import Capability
from src.models.capability_audit import CapabilityAudit
from src.models.worker import Worker
from src.utils.id_gen import generate_id

logger = logging.getLogger(__name__)


# ── 写入 ──────────────────────────────────────────────────────────


async def write_capability_audit(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    capability_id: str,
    authorization_request_id: str | None,
    exit_code: int,
    duration_ms: int,
    outcome: str,
    actor_type: str,
    actor_id: str,
) -> CapabilityAudit:
    """记录一条 capability 执行审计。

    在 report_execution 完成后调用。
    自动解析 capability name 作为 command 字段值。

    Args:
        project_id: 所属 Project
        worker_id: 执行 capability 的 Worker
        capability_id: capability 标识（如 shell_dangerous）
        authorization_request_id: 关联的授权请求 ID
        exit_code: 进程退出码
        duration_ms: 执行耗时（毫秒）
        outcome: success | failure
        actor_type: 执行者类型
        actor_id: 执行者 ID
    """
    # 解析 capability name 作为 command
    command = None
    if capability_id:
        result = await db.execute(
            select(Capability.name).where(Capability.id == capability_id)
        )
        name = result.scalar_one_or_none()
        command = name

    audit = CapabilityAudit(
        id=generate_id("capability_audit"),
        project_id=project_id,
        worker_id=worker_id,
        capability_id=capability_id,
        authorization_request_id=authorization_request_id,
        command=command,
        exit_code=exit_code,
        duration_ms=duration_ms,
        outcome=outcome,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    db.add(audit)
    await db.flush()

    logger.info(
        "capability_audit_recorded",
        extra={
            "audit_id": audit.id,
            "worker_id": worker_id,
            "capability_id": capability_id,
            "outcome": outcome,
            "duration_ms": duration_ms,
        },
    )

    return audit


# ── 查询 ──────────────────────────────────────────────────────────


async def list_capability_audits(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str | None = None,
    capability_id: str | None = None,
    outcome: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[CapabilityAudit], str | None, int | None]:
    """分页查询能力执行审计记录，按创建时间降序。

    支持按 worker_id、capability_id、outcome、日期范围筛选。
    使用 cursor-based 分页（cursor = 上一页最后一条记录的 id）。

    Returns:
        (items, next_cursor, total)
    """
    conditions: list = [CapabilityAudit.project_id == project_id]
    if worker_id:
        conditions.append(CapabilityAudit.worker_id == worker_id)
    if capability_id:
        conditions.append(CapabilityAudit.capability_id == capability_id)
    if outcome:
        conditions.append(CapabilityAudit.outcome == outcome)
    if date_from:
        dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        conditions.append(CapabilityAudit.created_at >= dt_from)
    if date_to:
        dt_to = datetime.fromisoformat(date_to).replace(
            hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc
        )
        conditions.append(CapabilityAudit.created_at <= dt_to)
    if cursor:
        conditions.append(CapabilityAudit.id < cursor)

    stmt = (
        select(CapabilityAudit)
        .where(*conditions)
        .order_by(CapabilityAudit.created_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = (
        select(func.count(CapabilityAudit.id)).where(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total
