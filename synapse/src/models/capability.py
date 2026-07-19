"""Capability 模型 — Worker 声明可执行的操作能力。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class Capability(Base, AuditMixin):
    __tablename__ = "capability"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("worker.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    input_schema: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    output_schema: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    rate_limit: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # 关联关系
    worker: Mapped["Worker"] = relationship("Worker", back_populates="capabilities")
