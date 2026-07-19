"""Verification 模型 — Task 完成前必须满足的验收条件。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants import VerificationStatus
from src.models.base import AuditMixin, Base


class Verification(Base, AuditMixin):
    __tablename__ = "verification"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    criteria: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=VerificationStatus.PENDING)
    verified_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # ── P8-B6：二级验收 ────────────────────────────────────────────────
    review_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 关联关系
    task: Mapped["Task"] = relationship("Task", back_populates="verifications")
