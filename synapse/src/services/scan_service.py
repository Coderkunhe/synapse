"""ComplianceScan 服务 — 编排规则执行、持久化结果、记录事件。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ScanTarget
from src.exceptions import NotFoundError
from src.models.scan import ScanResult
from src.constants import ScanVerdictStatus
from src.services.event_store import event_store
from src.services.scan_rules import ScanVerdict, rule_registry
from src.utils.id_gen import generate_id


async def execute_scan(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> ScanResult:
    """对目标执行所有适用规则，持久化 ScanResult。

    规则通过 ``asyncio.gather`` 并发执行 — 每条规则都是纯读取，
    共享同一异步 session 是安全的。
    """
    rules = rule_registry.for_target(target_type)

    if not rules:
        # 该目标类型无注册规则 — 仍然记录扫描
        verdicts: list[ScanVerdict] = []
    else:
        results = await asyncio.gather(
            *[r.check(db, target_id) for r in rules], return_exceptions=True
        )
        verdicts = []
        for rule, result in zip(rules, results):
            if isinstance(result, Exception):
                verdicts.append(
                    ScanVerdict(
                        rule_id=rule.rule_id,
                        status=ScanVerdictStatus.FAIL,
                        detail=f"Rule execution error: {result}",
                    )
                )
            else:
                verdicts.append(result)

    # 计算汇总
    summary_pass = sum(1 for v in verdicts if v.status == ScanVerdictStatus.PASS)
    summary_fail = sum(1 for v in verdicts if v.status == ScanVerdictStatus.FAIL)
    summary_warn = sum(1 for v in verdicts if v.status == ScanVerdictStatus.WARN)

    # 持久化
    scan = ScanResult(
        id=generate_id("scan_result"),
        target_type=target_type,
        target_id=target_id,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        rules_checked=json.dumps(
            [{"rule_id": v.rule_id, "status": v.status, "detail": v.detail}
             for v in verdicts],
            ensure_ascii=False,
        ),
        summary_pass=summary_pass,
        summary_fail=summary_fail,
        summary_warn=summary_warn,
        create_user_id=actor_id,
    )
    db.add(scan)

    await event_store.record(
        db,
        event_type="scan.executed",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=f"scan:{target_type}" if target_type else "scan",
        target_id=scan.id,
        payload={
            "target_type": target_type,
            "target_id": target_id,
            "summary": {"pass": summary_pass, "fail": summary_fail, "warn": summary_warn},
        },
    )

    return scan


def scan_to_response(scan: ScanResult) -> dict:
    """将 ScanResult ORM 对象转换为响应字典，含 JSON 反序列化。"""
    return {
        "id": scan.id,
        "target_type": scan.target_type,
        "target_id": scan.target_id,
        "actor_type": scan.actor_type,
        "actor_id": scan.actor_id,
        "rules_checked": json.loads(scan.rules_checked),
        "summary": {
            "pass": scan.summary_pass,
            "fail": scan.summary_fail,
            "warn": scan.summary_warn,
        },
        "is_disabled": scan.is_disabled,
        "create_user_id": scan.create_user_id,
        "last_update_user_id": scan.last_update_user_id,
        "remark": scan.remark,
        "version_no": scan.version_no,
        "created_at": scan.created_at,
        "updated_at": scan.updated_at,
    }


async def get_scan(db: AsyncSession, scan_id: str) -> ScanResult:
    """按 ID 获取 ScanResult，不存在则抛出 NotFoundError。"""
    scan = await db.get(ScanResult, scan_id)
    if scan is None:
        raise NotFoundError("scan", scan_id)
    return scan


async def list_scans(
    db: AsyncSession,
    team_id: str,
    *,
    target_type: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[ScanResult], str | None, int | None]:
    """团队的游标分页扫描列表，最新优先。

    可按 ``target_type`` 过滤。
    """
    from sqlalchemy import func, select

    conditions = [ScanResult.team_id == team_id]
    if target_type:
        conditions.append(ScanResult.target_type == target_type)
    if cursor:
        conditions.append(ScanResult.id < cursor)

    stmt = (
        select(ScanResult)
        .where(*conditions)
        .order_by(ScanResult.created_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_conditions = [ScanResult.team_id == team_id]
    if target_type:
        count_conditions.append(ScanResult.target_type == target_type)
    count_stmt = select(func.count(ScanResult.id)).where(*count_conditions)
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total
