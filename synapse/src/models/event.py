"""Event 模型 — 所有状态变更的不可变只追加记录。

Event 是 Synapse 的"账本"。所有状态都是 event 的投影。
无 UPDATE，无 DELETE — 一次写入，多次读取。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, _utcnow


class Event(Base):
    __tablename__ = "event"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("team.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    payload: Mapped[str] = mapped_column(String(8000), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )
    create_user_id: Mapped[str] = mapped_column(
        String(40), nullable=False, default="system", server_default=text("'system'"),
        comment="触发此事件的用户或 agent（系统事件标记为 'system'）",
    )

    # 注意：无 updated_at 列。Event 不可变。
    # 注意：此模型无 setter 方法。Event 仅通过 event_store.record() 创建。

    # 关联关系
    team: Mapped["Team"] = relationship("Team", back_populates="events")
    task: Mapped["Task | None"] = relationship(
        "Task",
        back_populates="events",
        primaryjoin="foreign(Event.target_id) == Task.id",
        viewonly=True,
    )
