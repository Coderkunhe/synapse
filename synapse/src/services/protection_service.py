"""保护报告 Service — ProtectionReport CRUD + 骨架检测逻辑。

P10-B36: 议题 ⑥ Service 层 — 保护报告 Service。
P10-B37+ : 三个检测模式的实际分析逻辑（cross_project_access /
sensitive_overlap / capability_drift）在后续 Batch 实现。

MVP 策略：B36 提供完整 CRUD，允许手动创建报告（status=pending）。
run_report() 留骨架——调用方持有事务，不 commit。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import EventType
from src.exceptions import NotFoundError
from src.models.protection_report import ProtectionReport
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ── 查询辅助 ──────────────────────────────────────────────────────


async def get_report(
    db: AsyncSession,
    report_id: str,
) -> ProtectionReport:
    """按 ID 获取保护报告，不存在则 raise NotFoundError。"""
    result = await db.execute(
        select(ProtectionReport).where(ProtectionReport.id == report_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("ProtectionReport", report_id)
    return record


async def list_reports(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    report_type: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[ProtectionReport], str | None, int | None]:
    """分页查询保护报告，按创建时间降序。

    支持按 project_id、report_type、status 筛选。
    返回 (items, next_cursor, total)。
    """
    conditions: list = []
    if project_id:
        conditions.append(ProtectionReport.project_id == project_id)
    if report_type:
        conditions.append(ProtectionReport.report_type == report_type)
    if status:
        conditions.append(ProtectionReport.status == status)
    if cursor:
        conditions.append(ProtectionReport.id < cursor)

    stmt = (
        select(ProtectionReport)
        .where(*conditions)
        .order_by(ProtectionReport.created_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = (
        select(func.count(ProtectionReport.id)).where(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total


# ── 写入 ──────────────────────────────────────────────────────────


async def create_report(
    db: AsyncSession,
    *,
    project_id: str,
    report_type: str,
    triggered_by: str = "manual",
    parameters: dict | None = None,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> ProtectionReport:
    """创建保护报告（status=pending）。

    三种报告类型（来自 ProtectionReportType 枚举）：
    - cross_project_access: 跨 Project 访问检测
    - sensitive_overlap: 敏感 Worker 重叠检测
    - capability_drift: Worker 能力漂移检测

    触发方式：
    - manual: 手动触发（管理员/STEWARD 角色）
    - scheduled: 定时任务触发
    """
    import json

    now = datetime.now(timezone.utc)
    report = ProtectionReport(
        id=generate_id("protection_report"),
        project_id=project_id,
        report_type=report_type,
        status="pending",
        triggered_by=triggered_by,
        parameters_json=json.dumps(parameters) if parameters else None,
    )
    db.add(report)
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.PROTECTION_REPORT_CREATED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="protection_report",
        target_id=report.id,
        payload={
            "project_id": project_id,
            "report_type": report_type,
            "triggered_by": triggered_by,
        },
    )

    return report


async def run_report(
    db: AsyncSession,
    *,
    report_id: str,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> ProtectionReport:
    """执行保护报告检测 — pending → running → completed/failed。

    B36 骨架实现：执行基本的状态转换 + event 记录。
    三个检测模式的实际分析逻辑在 P10-B37+ 实现。
    """
    import json

    report = await get_report(db, report_id)

    if report.status != "pending":
        from src.exceptions import InvalidStateTransition
        raise InvalidStateTransition(
            entity_type="ProtectionReport",
            entity_id=report_id,
            from_status=report.status,
            to_status="running",
        )

    now = datetime.now(timezone.utc)

    # ── 状态转换: pending → running ──
    report.status = "running"
    report.started_at = now
    await db.flush()

    # ── 骨架检测逻辑 ──
    # P10-B37+ : 根据 report_type 执行对应的分析逻辑
    # - cross_project_access: 查询 Worker 跨 Project 的 project_actor_roles
    # - sensitive_overlap: 查询具有敏感 capability 的 Worker 在多个 Project 重叠
    # - capability_drift: 查询 Worker capability 声明的时间序列变化
    try:
        findings: list[dict] = []
        risk_score: float = 0.0

        if report.report_type == "cross_project_access":
            findings, risk_score = await _detect_cross_project_access(
                db, report.project_id
            )
        elif report.report_type == "sensitive_overlap":
            findings, risk_score = await _detect_sensitive_overlap(
                db, report.project_id
            )
        elif report.report_type == "capability_drift":
            findings, risk_score = await _detect_capability_drift(
                db, report.project_id
            )

        # ── 状态转换: running → completed ──
        report.status = "completed"
        report.result_json = json.dumps({
            "findings": findings,
            "risk_score": risk_score,
            "total_findings": len(findings),
        }, default=str)
        report.completed_at = datetime.now(timezone.utc)

        await event_store.record(
            db,
            event_type=EventType.PROTECTION_REPORT_COMPLETED,
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="protection_report",
            target_id=report.id,
            payload={
                "report_type": report.report_type,
                "total_findings": len(findings),
                "risk_score": risk_score,
            },
        )
    except Exception:
        # ── 状态转换: running → failed ──
        report.status = "failed"
        report.completed_at = datetime.now(timezone.utc)
        # 不记录额外 event — failure 由 exception handler 记录

    await db.flush()
    return report


# ── 检测骨架（P10-B37+ 实现实际逻辑）─────────────────────────────


async def _detect_cross_project_access(
    db: AsyncSession, project_id: str
) -> tuple[list[dict], float]:
    """跨 Project 访问检测骨架。

    P10-B37+ : 查询本 Project 中具有其他 Project 角色的 Worker，
    分析跨 Project 资源访问模式是否异常。
    """
    # 骨架：返回空结果
    return [], 0.0


async def _detect_sensitive_overlap(
    db: AsyncSession, project_id: str
) -> tuple[list[dict], float]:
    """敏感 Worker 重叠检测骨架。

    P10-B37+ : 查询具有敏感 capability 的 Worker，
    检测其在多个 Project 中的重叠模式。
    """
    return [], 0.0


async def _detect_capability_drift(
    db: AsyncSession, project_id: str
) -> tuple[list[dict], float]:
    """Worker 能力漂移检测骨架。

    P10-B37+ : 查询 Worker capability 的历史变化，
    使用 Event 表追踪 capability 声明的时间序列漂移。
    """
    return [], 0.0
