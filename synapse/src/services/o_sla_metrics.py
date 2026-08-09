"""O SLA Metrics 服务 — O 响应性 SLA 自动度量 (P13-B12 · C11)。

从 Event 账本中计算 Orchestrator 响应时间：
- 对每个已提交的任务，查找 TASK_SUBMITTED → VERIFICATION_EXECUTED 的时间差
- 计算百分位（p50/p95/p99）+ SLA 达标率 + 违规列表

C11 验收标准：O 在 Task submit 后 5min 内开始 verification 的概率 ≥95%。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import EventType

logger = logging.getLogger(__name__)


async def compute_o_response_metrics(
    db: AsyncSession,
    window_hours: int = 24,
    sla_target_minutes: int = 5,
) -> dict:
    """计算 O 响应时间 SLA 指标。

    从 Event 表查询：
    1. 所有 TASK_SUBMITTED 事件（在时间窗口内）
    2. 对每个 task，找到第一个 VERIFICATION_EXECUTED 事件
    3. 时间差 = O 响应时间

    Args:
        db: 数据库会话。
        window_hours: 统计时间窗口（小时），默认 24h。
        sla_target_minutes: SLA 目标阈值（分钟），默认 5min。

    Returns:
        {
            "window_hours": 24,
            "sla_target_minutes": 5,
            "total_tasks": 10,
            "response_times_seconds": [120.0, 180.0, ...],
            "p50_seconds": 150.0,
            "p95_seconds": 280.0,
            "p99_seconds": 350.0,
            "min_seconds": 60.0,
            "max_seconds": 400.0,
            "mean_seconds": 180.0,
            "breach_count": 1,
            "sla_compliance_pct": 90.0,
            "breaches": [
                {"task_id": "tsk_...", "response_seconds": 350.0, "submitted_at": "..."},
            ],
        }
    """
    from src.models.event import Event

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)
    sla_target_seconds = sla_target_minutes * 60

    # ── Step 1: 查询窗口内的 TASK_SUBMITTED 事件 ──
    submitted_stmt = (
        select(Event)
        .where(
            Event.event_type == EventType.TASK_SUBMITTED,
            Event.created_at >= window_start,
        )
        .order_by(Event.created_at.asc())
    )
    submitted_result = await db.execute(submitted_stmt)
    submitted_events = submitted_result.scalars().all()

    if not submitted_events:
        return {
            "window_hours": window_hours,
            "sla_target_minutes": sla_target_minutes,
            "total_tasks": 0,
            "response_times_seconds": [],
            "p50_seconds": None,
            "p95_seconds": None,
            "p99_seconds": None,
            "min_seconds": None,
            "max_seconds": None,
            "mean_seconds": None,
            "breach_count": 0,
            "sla_compliance_pct": None,
            "breaches": [],
        }

    # ── Step 2: 对每个 task，查找第一个 VERIFICATION_EXECUTED 事件 ──
    response_times: list[dict] = []  # {task_id, submitted_at, executed_at, seconds}

    for sub_evt in submitted_events:
        # 找到该 task 在 submitted 之后第一个 verification_executed 事件
        exec_stmt = (
            select(Event)
            .where(
                Event.event_type == EventType.VERIFICATION_EXECUTED,
                Event.target_type == "task",
                Event.target_id == sub_evt.target_id,
                Event.created_at >= sub_evt.created_at,
            )
            .order_by(Event.created_at.asc())
            .limit(1)
        )
        exec_result = await db.execute(exec_stmt)
        exec_evt = exec_result.scalars().first()

        if exec_evt is not None:
            delta = (exec_evt.created_at - sub_evt.created_at).total_seconds()
            response_times.append(
                {
                    "task_id": sub_evt.target_id,
                    "submitted_at": sub_evt.created_at.isoformat(),
                    "executed_at": exec_evt.created_at.isoformat(),
                    "seconds": round(delta, 1),
                }
            )

    if not response_times:
        return {
            "window_hours": window_hours,
            "sla_target_minutes": sla_target_minutes,
            "total_tasks": len(submitted_events),
            "response_times_seconds": [],
            "p50_seconds": None,
            "p95_seconds": None,
            "p99_seconds": None,
            "min_seconds": None,
            "max_seconds": None,
            "mean_seconds": None,
            "breach_count": 0,
            "sla_compliance_pct": None,
            "breaches": [],
            "note": "No verification_executed events found — O may not have processed any tasks yet in this window.",
        }

    # ── Step 3: 计算统计指标 ──
    seconds_list = sorted(r["seconds"] for r in response_times)
    total = len(seconds_list)
    breaches = [r for r in response_times if r["seconds"] > sla_target_seconds]

    return {
        "window_hours": window_hours,
        "sla_target_minutes": sla_target_minutes,
        "total_tasks": len(submitted_events),
        "tasks_with_verification": total,
        "response_times_seconds": seconds_list,
        "p50_seconds": _percentile(seconds_list, 50),
        "p95_seconds": _percentile(seconds_list, 95),
        "p99_seconds": _percentile(seconds_list, 99),
        "min_seconds": round(seconds_list[0], 1),
        "max_seconds": round(seconds_list[-1], 1),
        "mean_seconds": round(sum(seconds_list) / total, 1),
        "breach_count": len(breaches),
        "sla_compliance_pct": round((total - len(breaches)) / total * 100, 1),
        "breaches": sorted(breaches, key=lambda r: r["seconds"], reverse=True)[:20],
    }


def _percentile(sorted_values: list[float], pct: int) -> float:
    """计算百分位数（使用最近秩方法，与 NumPy linear interpolation 相近）。

    Args:
        sorted_values: 已排序的数值列表。
        pct: 百分位（0-100）。

    Returns:
        百分位数值，四舍五入到 1 位小数。
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    # Nearest-rank method: index = ceil(pct/100 * n) - 1
    idx = max(0, min(n - 1, int((pct / 100.0) * n + 0.5) - 1))
    # Linear interpolation for fractional index (closer to NumPy behavior)
    rank = (pct / 100.0) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac, 1)
