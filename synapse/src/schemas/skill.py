"""Skill schema — Skill CRUD 的请求/响应形态。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


class SkillCreate(BaseModel):
    """创建 Skill 定义的请求体。"""

    name: str = Field(..., min_length=1, max_length=200)
    version: str = Field(
        default="1.0.0",
        pattern=r"^\d+\.\d+\.\d+$",
    )
    template_md: str = Field(..., min_length=1)
    protocol_spec: dict | None = None
    scan_rule_ids: list[str] | None = None
    metadata_: dict | None = Field(None, alias="metadata")


class SkillUpdate(BaseModel):
    """更新 Skill 定义的请求体 — 所有字段可选。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    version: str | None = Field(None, pattern=r"^\d+\.\d+\.\d+$")
    template_md: str | None = Field(None, min_length=1)
    status: str | None = Field(None, pattern=r"^(active|deprecated)$")
    protocol_spec: dict | None = None
    scan_rule_ids: list[str] | None = None
    metadata_: dict | None = Field(None, alias="metadata")


class SkillResponse(AuditFields):
    """Skill 读取操作的响应体。"""

    id: str
    team_id: str
    name: str
    version: str
    status: str
    template_md: str
    protocol_spec: dict | None = None
    scan_rule_ids: list[str] | None = None
    metadata_: dict | None = Field(None, alias="metadata")

    model_config = {"from_attributes": True, "populate_by_name": True}
