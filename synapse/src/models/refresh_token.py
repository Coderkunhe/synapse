"""RefreshToken 模型 — OAuth 刷新令牌存储，含轮换家族追踪。

每个 token 属于一个家族。刷新时：旧 token 被撤销，同一家族内创建新 token。
若已撤销的 token 被重放（重放攻击），整个家族将被撤销。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import AuditMixin, Base


class RefreshToken(Base, AuditMixin):
    __tablename__ = "refresh_token"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    member_id: Mapped[str] = mapped_column(
        ForeignKey("member.id"), nullable=True, index=True,
        comment="P10-B9: nullable for new User-based auth — legacy OAuth path",
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id"), nullable=True, index=True,
        comment="P10-B9: FK to User for email/password auth — NULL for legacy OAuth",
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
