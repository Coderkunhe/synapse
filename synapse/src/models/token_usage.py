"""TokenUsage 模型 — Worker token 消耗的不可变只追加记录。

每一条记录代表一次 LLM 调用的 token 消耗明细。
只增不删不改 — 同 Event 模型，TokenUsage 是消耗维度的"账本"。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, _utcnow


class TokenUsage(Base, AuditMixin):
    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("task.id"), nullable=True, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("project.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    completion_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    cost: Mapped[str | None] = mapped_column(String(30), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )
    metadata_: Mapped[str | None] = mapped_column(
        "metadata", String(4000), nullable=True
    )

    # 关联关系
    worker: Mapped["Worker"] = relationship("Worker")
    task: Mapped["Task | None"] = relationship("Task")
    project: Mapped["Project | None"] = relationship("Project")
