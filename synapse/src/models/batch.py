"""Batch 模型 — 分布式执行中的最小分配单元（执行原子）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants import BatchStatus
from src.models.base import AuditMixin, Base


class Batch(Base, AuditMixin):
    __tablename__ = "batch"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BatchStatus.OPEN)
    order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── 结构化编号 (P9-B6) ────────────────────────────────────────────
    phase: Mapped[str | None] = mapped_column(String(10), nullable=True)
    batch_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Batch 原子性 (P9-B57) ───────────────────────────────────────────
    assigned_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("worker.id"), nullable=True, index=True,
        comment="该 Batch 分配给的 Worker — 一个 Batch 只能分配给一个 Worker"
    )

    # ── Workflow 归属 (P10-B24) ───────────────────────────────────────────
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow.id"), nullable=True, index=True,
        comment="所属 Workflow — Batch 作为 Workflow 内的执行原子",
    )

    # 关联关系
    project: Mapped["Project"] = relationship("Project", back_populates="batches")
    workflow: Mapped["Workflow | None"] = relationship(
        "Workflow", back_populates="batches",
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="batch")
    assigned_worker: Mapped["Worker | None"] = relationship(
        "Worker", foreign_keys=[assigned_worker_id]
    )
