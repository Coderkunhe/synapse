"""批次 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, Field

from src.schemas.common import AuditFields


class BatchCreate(BaseModel):
    """创建批次的请求体。"""

    name: str = Field(..., max_length=200)
    description: str | None = None
    order: int | None = None
    phase: str | None = Field(None, max_length=10)
    batch_number: int | None = None


class BatchUpdate(BaseModel):
    """更新批次的请求体。"""

    name: str | None = Field(None, max_length=200)
    description: str | None = None
    order: int | None = None
    phase: str | None = Field(None, max_length=10)
    batch_number: int | None = None


class BatchAssignRequest(BaseModel):
    """Batch 分配请求 — 将 Batch 分配给一个 Worker（P9-B57 · P7-007 分配原子）。"""

    worker_id: str = Field(
        ...,
        max_length=40,
        description="目标 Worker 的 ID",
        validation_alias=AliasChoices("worker_id", "agent_id"),
    )


class BatchResponse(AuditFields):
    """批次读取操作的响应体。"""

    id: str
    project_id: str
    name: str
    description: str | None = None
    status: str
    order: int | None = None
    completed_at: datetime | None = None
    phase: str | None = None
    batch_number: int | None = None
    assigned_to: str | None = None

    model_config = {"from_attributes": True}
