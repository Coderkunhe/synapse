"""DecisionAudit 模型 — 决策审计记录。

议题 ⑥（保护报告+熔断+决策审计）数据基础层。

不可变审计日志 — 每条授权决策（批准/拒绝/过期/取消/自动授权）都记录。
为远期信任分（trust score）数据基础。

注意：本模型不继承 AuditMixin。与 Event 模型对齐 — 审计记录只追加、不更新、不软删除。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（Python 侧计算）。"""
    from datetime import timezone
    return datetime.now(timezone.utc)


class DecisionAudit(Base):
    __tablename__ = "decision_audits"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── 关联授权请求 ──
    authorization_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("authorization_requests.id"), nullable=True, index=True,
        comment="关联的授权请求 — 系统自动决策（expire/cancel/auto_grant）可能为空",
    )

    # ── 决策类型 ──
    decision_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="approve | deny | expire | cancel | auto_grant",
    )

    # ── 决策者 ──
    actor_type: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="worker | human | system — 决策者类型",
    )
    actor_id: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="决策者 ID",
    )

    # ── 上下文 ──
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True,
        comment="所属 Project",
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="被决策的 Worker",
    )

    # ── 风险评估 ──
    risk_level: Mapped[str] = mapped_column(
        String(10), nullable=False, default="low",
        comment="low | medium | high | critical — 决策时的风险评估",
    )

    # ── 决策理由 ──
    reason: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="决策理由 — 人类可读的决策说明",
    )

    # ── 上下文 ──
    context_json: Mapped[str | None] = mapped_column(
        String(4000), nullable=True,
        comment="决策上下文 (JSON) — 当时的熔断状态、保护报告引用等",
    )

    # ── 时间戳（仅创建，不可更新）──
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, server_default=func.now(),
        comment="决策时间",
    )
    create_user_id: Mapped[str] = mapped_column(
        String(40), nullable=False, default="system",
        comment="记录创建者 ID",
    )

    # ── 关联 ──
    authorization_request: Mapped["AuthorizationRequest | None"] = relationship(
        "AuthorizationRequest",
    )
    project: Mapped["Project"] = relationship("Project")
    worker: Mapped["Worker"] = relationship("Worker")
