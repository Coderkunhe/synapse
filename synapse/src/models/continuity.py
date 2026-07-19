"""ContinuitySnapshot 模型 — 跨会话任务追踪的持久化检查点。

每个快照捕获某一时刻的未完成任务集合，使 TaskContinuityDetector
能跨检查点比对并识别进行中/已解决项。
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import AuditMixin, Base


class ContinuitySnapshot(Base, AuditMixin):
    """项目未完成任务的某时刻快照。

    由 TaskContinuityDetector.save_snapshot() 写入，
    由 generate_summary() 回读以跨检查点比对。

    created_at + updated_at 继承自 TimestampMixin。
    """

    __tablename__ = "continuity_snapshot"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True
    )
    last_activity_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    unfinished_tasks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
