"""PasswordResetToken 模型 — 密码重置令牌存储。P10-B12。

每次忘记密码请求创建一条新记录。令牌在验证后标记为已使用（不可复用）。
过期令牌无法使用。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import AuditMixin, Base


class PasswordResetToken(Base, AuditMixin):
    __tablename__ = "password_reset_token"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="SHA-256 hex digest of the plaintext reset token",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="Token expires 1 hour after creation",
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="Set when the token is successfully used to reset password",
    )
    created_by_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="管理员创建的重置令牌 — True = 由管理员触发（非用户自主 forgot-password）",
    )
