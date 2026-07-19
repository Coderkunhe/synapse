"""SQLAlchemy 声明式基类和通用 mixin。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 Synapse 模型的声明式基类。"""
    pass


def _utcnow() -> datetime:
    """返回当前 UTC 时间（Python 侧计算，避免 server_default 的 greenlet 问题）。"""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """为模型添加 created_at 和 updated_at 列。

    注意：onupdate 使用 Python 侧可调用对象 (_utcnow) 而非
    SQL func.now()，以避免 SQLAlchemy 异步 greenlet 问题。
    当 func.now() 用作 onupdate 时，SQLAlchemy 在 UPDATE 后将列标记为
    "expired" 以获取服务器生成的值。该获取操作在 ASGITransport 下触发
    MissingGreenlet 错误。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AuditMixin(TimestampMixin):
    """基线审计字段 — 所有业务表强制使用。

    继承链：Base → TimestampMixin → AuditMixin。
    TimestampMixin 提供：created_at, updated_at。
    AuditMixin 追加：is_disabled, create_user_id, last_update_user_id,
    remark, version_no。

    按 development-standards.md §1.1 — 所有业务表必须继承 AuditMixin，
    除非显式豁免（如 event 表）。
    """

    is_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"), index=True,
        comment="软删除/禁用标记",
    )
    create_user_id: Mapped[str] = mapped_column(
        String(40), nullable=False, default="system", server_default=text("'system'"),
        comment="创建者 ID（member_id 或 worker_id）",
    )
    last_update_user_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
        comment="最后更新者 ID",
    )
    remark: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="备注/说明",
    )
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="乐观锁版本号",
    )
