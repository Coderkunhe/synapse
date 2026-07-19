"""Member 模型 — 人类用户在 Team 中的身份。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, _utcnow


class Member(Base, AuditMixin):
    __tablename__ = "member"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_member_team_user"),
        UniqueConstraint("team_id", "oauth_provider", "oauth_subject", name="uq_member_oauth"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("team.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # OAuth 身份（可为空 — 仅对 OAuth 认证的成员设置）
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    oauth_subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # 关联关系
    team: Mapped["Team"] = relationship("Team", back_populates="members")
