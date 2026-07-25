"""CapabilityAudit schemas — 能力执行审计查询响应模型。

P11-B57 (GAP-8): 只读查询 schema，审计记录不可变。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import CursorPage


class CapabilityAuditResponse(BaseModel):
    """单条审计记录响应。"""

    id: str
    project_id: str
    worker_id: str
    capability_id: str
    authorization_request_id: str | None = None
    command: str | None = None
    exit_code: int
    duration_ms: int
    outcome: str
    actor_type: str
    actor_id: str
    created_at: datetime

    # 富化字段
    worker_name: str | None = None

    model_config = {"from_attributes": True}


class CapabilityAuditListParams(BaseModel):
    """审计列表查询参数（不用于请求体校验，仅文档化）。"""

    worker_id: str | None = Field(None, description="按 Worker 过滤")
    capability_id: str | None = Field(None, description="按 capability 过滤")
    outcome: str | None = Field(None, pattern=r"^(success|failure)$", description="按结果过滤")
    date_from: str | None = Field(None, description="起始日期 (YYYY-MM-DD)")
    date_to: str | None = Field(None, description="截止日期 (YYYY-MM-DD)")
    cursor: str | None = Field(None, max_length=80, description="分页游标")
    limit: int = Field(50, ge=1, le=100, description="每页条数")


CapabilityAuditPage = CursorPage[CapabilityAuditResponse]
