"""UserPushSubscription 模型 — 浏览器 WebPush 订阅。

议题 ⑦ 通知通道第 4 通道（P10-B44 · S-066）。

每个 User 可以有多个订阅（多浏览器/多设备）。
(user_id, endpoint) 唯一 — 同一用户同一浏览器只存一份。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class UserPushSubscription(Base, AuditMixin):
    __tablename__ = "user_push_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "endpoint", name="uq_push_subscription"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── 归属 ──
    user_id: Mapped[str] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True,
        comment="User ID — 订阅所属用户",
    )

    # ── 浏览器推送订阅信息 (RFC 8291) ──
    endpoint: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="浏览器推送服务 URL（如 fcm.googleapis.com）",
    )
    p256dh_key: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="客户端 ECDH 公钥（base64url）",
    )
    auth_secret: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="认证密钥（base64url）",
    )

    # ── 设备信息 ──
    device_info: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="navigator.userAgent 等设备标识信息",
    )

    # ── 关系 ──
    user: Mapped["User"] = relationship(  # noqa: F821
        back_populates="push_subscriptions",
        lazy="selectin",
    )
