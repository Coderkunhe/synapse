"""共享 schema 类型：分页、错误、角色身份。"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from src.constants import ActorType

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    """基于游标的分页响应（protocol.md §2.1）。"""

    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class ErrorResponse(BaseModel):
    """标准错误格式（protocol.md §9.1）。"""

    code: str
    message: str
    details: dict | None = None


class ErrorDetail(BaseModel):
    """错误响应信封的包装器。"""

    error: ErrorResponse


class ActorInfo(BaseModel):
    """注入请求上下文的统一角色身份（D-018）。"""

    actor_type: ActorType
    actor_id: str
    team_id: str
    role: str | None = None
    name: str | None = None


class AuditFields(BaseModel):
    """所有业务表 Response schema 的审计字段。

    对应 SQLAlchemy AuditMixin（→ TimestampMixin）链：
    created_at / updated_at 来自 TimestampMixin；
    is_disabled / create_user_id / last_update_user_id / remark / version_no
    来自 AuditMixin。

    用法::

        class FooResponse(AuditFields):
            id: str
            name: str
            # ... 业务字段 ...
            model_config = {"from_attributes": True}  # 继承自 AuditFields
    """

    is_disabled: bool
    create_user_id: str
    last_update_user_id: str | None = None
    remark: str | None = None
    version_no: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
