"""成员 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


class MemberCreate(BaseModel):
    """邀请成员加入团队的请求体。"""

    user_id: str = Field(..., max_length=40)
    display_name: str = Field(..., max_length=100)
    role: str = Field(default="member", pattern=r"^(admin|lead|member)$")


class MemberUpdate(BaseModel):
    """更新成员角色的请求体。"""

    role: str = Field(..., pattern=r"^(admin|lead|member)$")


class MemberResponse(AuditFields):
    """成员读取操作的响应体。"""

    id: str
    team_id: str
    user_id: str
    display_name: str
    role: str
    joined_at: datetime
    last_active_at: datetime | None = None
