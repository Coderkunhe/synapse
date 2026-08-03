"""TaskWorkerConversation schema — A2A 结构化消息的 API 序列化层。

P10-B28: 议题 5 A2A 协议 — 数据基础层。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


# ═════════════════════════════════════════════════════════════════════════
# 请求体
# ═════════════════════════════════════════════════════════════════════════


class ConversationMessageCreate(BaseModel):
    """创建 A2A 消息的请求体。

    message_type 为 handoff 时，后续 Service 层会触发 task.assign AuthorizationRequest。
    """

    task_id: str = Field(..., description="对话归属的任务 ID")
    workflow_id: str | None = Field(None, description="可选 Workflow 上下文")
    message_type: str = Field(
        ...,
        pattern=r"^(clarification|blocking|review_request|handoff|proposal)$",
    )
    body: str = Field(..., min_length=1, description="消息正文，支持 @worker:name / @role:rolename 语法")
    in_reply_to_id: str | None = Field(None, description="回复目标消息 ID")
    proposal_status: str | None = Field(None, pattern=r"^(pending|confirmed|rejected)$", description="提案状态 — O 提案→Human 确认 (P11-B117)")


class ConversationMessageUpdate(BaseModel):
    """更新 A2A 消息的请求体（所有字段可选）。

    支持：标记 resolved、编辑正文、更新解决状态、更新提案状态。
    """

    body: str | None = Field(None, min_length=1)
    is_resolved: bool | None = None
    proposal_status: str | None = Field(None, pattern=r"^(pending|confirmed|rejected)$", description="更新提案状态 (P11-B117)")


# ═════════════════════════════════════════════════════════════════════════
# 响应体
# ═════════════════════════════════════════════════════════════════════════


class ConversationMessageResponse(AuditFields):
    """A2A 消息的完整响应体。"""

    id: str
    task_id: str
    workflow_id: str | None = None
    sender_worker_id: str
    message_type: str
    body: str
    mentions_json: str | None = None
    in_reply_to_id: str | None = None
    authorization_request_id: str | None = None
    is_resolved: bool
    resolved_at: datetime | None = None
    resolved_by_worker_id: str | None = None
    proposal_status: str | None = None

    model_config = {"from_attributes": True}
