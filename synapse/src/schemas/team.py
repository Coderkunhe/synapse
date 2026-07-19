"""Team schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


class TeamCreate(BaseModel):
    """创建 Team 的请求体。"""
    name: str = Field(..., max_length=100)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=2048)


class TeamUpdate(BaseModel):
    """更新 Team 的请求体（所有字段可选）。"""
    name: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=2000)
    avatar_url: str | None = Field(None, max_length=2048)


class TeamResponse(AuditFields):
    """Team 读取操作的响应体。"""
    id: str
    name: str
    slug: str
    description: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}
