"""CapabilityAudit schemas — 能力执行审计查询响应 + 创建请求模型。

P11-B57 (GAP-8): 只读查询 schema，审计记录不可变。
P11-B100 (GAP-8 补刀): 安全命令审计持久化 — POST 请求 schema。
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


class CapabilityAuditCreate(BaseModel):
    """能力执行审计创建请求 — P11-B100。

    Worker 在 capability 执行完成后调用此 schema 上报审计记录。
    安全命令（免审批）和授权命令（有 AuthorizationRequest）均可使用。
    worker_id / project_id / actor_type / actor_id 由服务端从认证上下文提取，
    不由客户端传入。
    """

    capability_id: str = Field(..., description="能力 ID — 如 shell_dangerous")
    command: str | None = Field(None, max_length=500, description="人类可读的执行命令描述")
    exit_code: int = Field(..., description="进程退出码")
    duration_ms: int = Field(..., description="执行耗时（毫秒）")
    outcome: str = Field(..., pattern=r"^(success|failure)$", description="执行结果")
    authorization_request_id: str | None = Field(
        None, max_length=40, description="关联的授权请求 ID — 安全命令此字段为 null"
    )


CapabilityAuditPage = CursorPage[CapabilityAuditResponse]
