"""User 模型 — 认证身份层。P10 ADR-004 四实体架构的一部分。"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class User(Base, AuditMixin):
    """认证身份 — 你是谁，怎么登录进来的。

    User 是认证层的顶层实体。一个 User 可以有多种登录方式
    （GitHub OAuth、Email/Password、Google OAuth），通过
    UserAuthMethod 关联。

    User 本身不做任何"执行"操作 — 执行通过关联的 Worker 进行。
    人类 User 注册后自动获得一条 actor_type='human' 的 Worker 记录。
    """

    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="bcrypt hash — NULL for OAuth-only users",
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="软禁用标记 — False = 账号已停用",
    )
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="超级管理员标记 — True = 可管理所有 Project 和 User",
    )
    force_password_change: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="强制密码修改标记 — True = 下次登录必须改密",
    )

    # 关联关系
    auth_methods: Mapped[list["UserAuthMethod"]] = relationship(
        "UserAuthMethod", back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list["UserPushSubscription"]] = relationship(
        "UserPushSubscription", back_populates="user", cascade="all, delete-orphan"
    )
