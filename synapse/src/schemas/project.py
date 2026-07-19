"""Project schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


class ProjectCreate(BaseModel):
    """创建 Project 的请求体。"""
    name: str = Field(..., max_length=200)
    slug: str = Field(..., max_length=200, pattern=r"^[a-z0-9-]+$")
    description: str | None = None
    default_branch: str | None = Field(None, max_length=200)
    git_repo_url: str | None = Field(None, max_length=2048)
    api_docs_url: str | None = Field(None, max_length=2048)
    frontend_test_url: str | None = Field(None, max_length=2048)
    webhook_url: str | None = Field(None, max_length=2048)
    use_phase_mode: bool = False
    current_phase: str | None = Field(None, max_length=200)
    organization: str | None = Field(None, max_length=200)
    metadata: dict | None = None
    is_protected: bool = False


class ProjectUpdate(BaseModel):
    """更新 Project 的请求体（所有字段可选）。"""
    name: str | None = Field(None, max_length=200)
    description: str | None = None
    default_branch: str | None = Field(None, max_length=200)
    git_repo_url: str | None = Field(None, max_length=2048)
    api_docs_url: str | None = Field(None, max_length=2048)
    frontend_test_url: str | None = Field(None, max_length=2048)
    webhook_url: str | None = Field(None, max_length=2048)
    use_phase_mode: bool | None = None
    current_phase: str | None = Field(None, max_length=200)
    organization: str | None = Field(None, max_length=200)
    metadata: dict | None = None
    is_protected: bool | None = None


class ProjectProtectionUpdate(BaseModel):
    """切换 Project 保护标记的请求体。"""
    is_protected: bool


class ProjectResponse(AuditFields):
    """Project 读取操作的响应体。"""
    id: str
    team_id: str
    name: str
    slug: str
    description: str | None = None
    status: str
    default_branch: str | None = None
    git_repo_url: str | None = None
    api_docs_url: str | None = None
    frontend_test_url: str | None = None
    webhook_url: str | None = None
    use_phase_mode: bool = False
    current_phase: str | None = None
    organization: str | None = None
    metadata: dict | None = Field(None, validation_alias="metadata_")
    is_protected: bool = False
    archived_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}
