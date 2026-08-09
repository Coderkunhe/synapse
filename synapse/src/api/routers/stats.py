"""Stats API routes — O SLA 指标查询 (P13-B12 · C11)。

提供 Orchestrator 响应性 SLA 度量端点。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_db
from src.services.o_sla_metrics import compute_o_response_metrics

router = APIRouter(tags=["stats"])


@router.get("/stats/o-sla")
async def get_o_sla_metrics(
    window_hours: int = Query(
        None,
        ge=1,
        le=168,  # max 7 days
        description="统计时间窗口（小时）",
    ),
    sla_target_minutes: int = Query(
        None,
        ge=1,
        le=120,
        description="SLA 目标阈值（分钟）",
    ),
    db: AsyncSession = Depends(get_db),
):
    """查询 O 响应性 SLA 指标。

    从 Event 账本中计算 Orchestrator 的响应时间分布：
    - 每个 task 的 TASK_SUBMITTED → VERIFICATION_EXECUTED 时间差
    - 百分位（p50/p95/p99）+ SLA 达标率 + 违规列表

    **C11 验收标准**：O 在 Task submit 后 5min 内开始 verification 的概率 ≥95%。

    无需认证 — 运维端点。
    """
    w = window_hours if window_hours is not None else settings.o_sla_window_hours
    t = sla_target_minutes if sla_target_minutes is not None else settings.o_sla_target_minutes

    return await compute_o_response_metrics(
        db,
        window_hours=w,
        sla_target_minutes=t,
    )
