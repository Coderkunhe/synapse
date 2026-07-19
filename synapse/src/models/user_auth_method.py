"""UserAuthMethod 模型 — 多 OAuth provider 绑定。P10 ADR-004。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class UserAuthMethod(Base, AuditMixin):
    """User 与外部认证 provider 的绑定。

    一个 User 可以绑定多个认证方式（GitHub + Google + Email/Password）。
    (provider, subject) 组合全局唯一 — 同一个 OAuth 身份只能绑定一个 User。
    """

    __tablename__ = "user_auth_method"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_auth_method_provider_subject"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="认证提供商: github | google | email",
    )
    subject: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="provider 侧的用户标识（GitHub user ID / Google sub / email 地址）",
    )

    # 关联关系
    user: Mapped["User"] = relationship("User", back_populates="auth_methods")
