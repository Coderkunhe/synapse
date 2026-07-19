"""User schema。"""

from __future__ import annotations

from pydantic import BaseModel

from src.schemas.common import AuditFields


class UserResponse(AuditFields):
    """User 读取响应 — P10 阶段只读，暂无创建/更新端点。"""

    id: str
    email: str | None = None
    display_name: str
    avatar_url: str | None = None
    is_active: bool = True
    is_super_admin: bool = False
    force_password_change: bool = False

    # model_config 继承自 AuditFields（from_attributes=True）


class UserAuthMethodResponse(AuditFields):
    """User 绑定的认证方式。"""

    id: str
    user_id: str
    provider: str
    subject: str

    # model_config 继承自 AuditFields（from_attributes=True）
