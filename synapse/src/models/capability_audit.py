"""CapabilityAudit 模型 — 能力执行安全审计日志。

GAP-8 (P11-B57): 不可变审计记录 — 每次 capability 执行完成后写一条。
对齐 DecisionAudit 模式：不继承 AuditMixin，只追加、不更新、不软删除。

为 GAP-9（Worker 自主驱动）提供安全审计基础。
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


class CapabilityAudit(Base):
    __tablename__ = "capability_audits"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── 归属 ──
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True,
        comment="所属 Project",
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="执行 capability 的 Worker",
    )

    # ── capability 标识 ──
    capability_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="能力 ID — 如 shell_dangerous / git_force_push",
    )
    authorization_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("authorization_requests.id"), nullable=True, index=True,
        comment="关联的授权请求 — 未来非授权触发的审计可能为空",
    )

    # ── 执行详情 ──
    command: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="人类可读的执行命令描述",
    )
    exit_code: Mapped[int] = mapped_column(
        nullable=False,
        comment="进程退出码",
    )
    duration_ms: Mapped[int] = mapped_column(
        nullable=False,
        comment="执行耗时（毫秒）",
    )
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="success | failure",
    )

    # ── 执行者 ──
    actor_type: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="worker | human | system — 执行者类型",
    )
    actor_id: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="执行者 ID",
    )

    # ── 时间戳（仅创建，不可更新）──
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, server_default=func.now(),
        comment="审计记录创建时间",
    )
    create_user_id: Mapped[str] = mapped_column(
        String(40), nullable=False, default="system",
        comment="记录创建者 ID",
    )

    # ── 关联 ──
    project: Mapped["Project"] = relationship("Project")
    worker: Mapped["Worker"] = relationship("Worker")
    authorization_request: Mapped["AuthorizationRequest | None"] = relationship(
        "AuthorizationRequest",
    )
