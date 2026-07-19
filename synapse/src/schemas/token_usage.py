"""TokenUsage schema — token 消耗记录的请求/响应形态。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


class TokenUsageCreate(BaseModel):
    """记录一条 token 消耗的请求体。"""

    task_id: str | None = Field(None, max_length=40)
    project_id: str | None = Field(None, max_length=40)
    provider: str = Field(..., max_length=30)
    model: str = Field(..., max_length=100)
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    request_id: str | None = Field(None, max_length=255)
    recorded_at: datetime | None = None
    metadata_: dict | None = Field(None, alias="metadata")


class TokenUsageResponse(AuditFields):
    """TokenUsage 读取操作的响应体。

    total_tokens 是计算字段（= prompt + completion），不存 DB。
    """

    id: str
    worker_id: str
    task_id: str | None = None
    project_id: str | None = None
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: str | None = None
    request_id: str | None = None
    recorded_at: datetime
    metadata_: dict | None = Field(None, alias="metadata")

    model_config = {"from_attributes": True, "populate_by_name": True}
