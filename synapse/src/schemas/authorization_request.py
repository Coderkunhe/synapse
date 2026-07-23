"""AuthorizationRequest schema — 异步授权请求的 API 序列化层。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


# ═════════════════════════════════════════════════════════════════════════
# 请求体
# ═════════════════════════════════════════════════════════════════════════


class AuthorizationRequestCreate(BaseModel):
    """创建授权请求 — 由系统或 Worker 发起。

    按 request_type 区分必填字段组：
    - api_auth: operation 必填，target_resource_* 可选
    - interactive_prompt: prompt_type + prompt_message 必填，prompt_choices 可选（choice 类型时必填）
    """

    project_id: str
    worker_id: str
    request_type: str = Field(..., pattern=r"^(api_auth|interactive_prompt)$")

    # api_auth 字段组
    operation: str | None = Field(None, max_length=100)
    target_resource_type: str | None = Field(None, max_length=50)
    target_resource_id: str | None = Field(None, max_length=40)

    # interactive_prompt 字段组
    prompt_type: str | None = Field(None, pattern=r"^(confirm|choice|input)$")
    prompt_message: str | None = Field(None, max_length=2000)
    prompt_choices: list[str] | None = None

    # TTL（秒），默认 3600（1 小时）
    ttl_seconds: int = Field(3600, ge=60, le=86400)


class AuthorizationRequestRespond(BaseModel):
    """审批授权请求 — 人类对 pending 请求的响应。"""

    status: str = Field(..., pattern=r"^(approved|denied)$")
    response_note: str | None = Field(None, max_length=2000)
    response_data: str | None = Field(None, max_length=2000)
    # 描述: choice 类型的选择值 / input 类型的文本 / confirm 类型为 null


class AuthorizationRequestHeartbeat(BaseModel):
    """心跳续期请求 — Worker 定期发送以保持请求存活。"""

    pass  # 无额外字段，仅更新 last_heartbeat_at


# ═════════════════════════════════════════════════════════════════════════
# 响应体
# ═════════════════════════════════════════════════════════════════════════


class AuthorizationRequestResponse(AuditFields):
    """授权请求的完整响应体。"""

    id: str
    project_id: str
    worker_id: str
    request_type: str

    # api_auth 字段组
    operation: str | None = None
    target_resource_type: str | None = None
    target_resource_id: str | None = None

    # interactive_prompt 字段组
    prompt_type: str | None = None
    prompt_message: str | None = None
    prompt_choices: list[str] | None = None

    # 状态
    status: str

    # 审批/响应
    responded_by_worker_id: str | None = None
    responded_at: datetime | None = None
    response_note: str | None = None
    response_data: str | None = None

    # 存活
    expires_at: datetime
    last_heartbeat_at: datetime

    # 富化字段（非 ORM，由 endpoint 手动填充）
    worker_name: str | None = None
    responded_by_worker_name: str | None = None

    model_config = {"from_attributes": True}
