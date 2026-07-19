"""CircuitBreaker 模型 — 熔断器状态。

议题 ⑥（保护报告+熔断+决策审计）数据基础层。

三层熔断架构：
- L1 Worker 级: 连续失败 → pause（本表 target_type=worker）
- L2 Project 级: 异常激增 → open（本表 target_type=project）
- L3 全局级: 远期（不在本表建模）

状态机: CLOSED → OPEN → HALF_OPEN → CLOSED
每个 (target_type, target_id) 最多一条记录。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import AuditMixin, Base


class CircuitBreaker(Base, AuditMixin):
    __tablename__ = "circuit_breakers"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", name="uq_circuit_breaker_target"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── 目标 ──
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="worker | project — 熔断器目标类型",
    )
    target_id: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="worker.id 或 project.id — 熔断器目标 ID",
    )

    # ── 状态 ──
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="closed", index=True,
        comment="closed | open | half_open — 当前熔断状态",
    )

    # ── 失败计数 ──
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="当前窗口内的连续失败次数",
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="最后一次失败的时间",
    )

    # ── 熔断时间 ──
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="熔断打开时间（OPEN 状态开始时）",
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="冷却期结束时间 — 到达后允许 half_open 试探",
    )
