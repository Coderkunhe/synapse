"""AnalysisRecord 模型 — 不可变的结构化分析账本条目。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants import AnalysisType
from src.models.base import AuditMixin, Base


class AnalysisRecord(Base, AuditMixin):
    __tablename__ = "analysis_record"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    analysis_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AnalysisType.REQUIREMENT, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("batch.id"), nullable=True, index=True
    )
    metadata_: Mapped[str | None] = mapped_column("metadata", String(4000), nullable=True)

    # 关联关系
    project: Mapped["Project"] = relationship("Project")
    source_batch: Mapped["Batch"] = relationship("Batch")
