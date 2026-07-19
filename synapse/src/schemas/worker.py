"""Worker schema。"""

from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.schemas.common import AuditFields


class WorkerCreate(BaseModel):
    """注册新 Worker 的请求体（仅管理员）。"""
    name: str = Field(..., max_length=100)
    provider: Literal["claude", "codex", "custom"] = "claude"
    provider_model: str | None = Field(None, max_length=100)
    system_prompt: str | None = None
    metadata: dict | None = None
    batch_size: int = Field(default=3, ge=1, le=20, description="Worker 适合处理的最大 Batch 任务数")


class WorkerUpdate(BaseModel):
    """更新 Worker 配置的请求体。"""
    name: str | None = Field(None, max_length=100)
    provider_model: str | None = Field(None, max_length=100)
    system_prompt: str | None = None
    metadata: dict | None = None
    batch_size: int | None = Field(None, ge=1, le=20, description="Worker 适合处理的最大 Batch 任务数")


class WorkerHandshakeRequest(BaseModel):
    """Worker 握手的请求体（protocol.md §3.2）。

    capabilities 接受两种格式：
    - 简写: ["code.review", "task.update"] → 自动转为 CapabilityDeclaration
    - 完整: [{"name": "code.review", "description": "...", ...}]
    """
    worker_version: str = Field(default="0.0.0", max_length=50)
    capabilities: list[CapabilityDeclaration] = Field(default_factory=list)
    supported_events: list[str] = Field(default_factory=list)
    preferred_channel: Literal["websocket", "webhook"] = "websocket"

    @field_validator("capabilities", mode="before")
    @classmethod
    def normalize_capabilities(cls, v: list) -> list:
        """接受 str 或 dict，统一转为 CapabilityDeclaration 能消化的 dict。"""
        result = []
        for item in v:
            if isinstance(item, str):
                result.append({"name": item})
            else:
                result.append(item)
        return result


class CapabilityDeclaration(BaseModel):
    """Worker 握手期间声明的能力。"""
    name: str = Field(..., max_length=100)
    description: str | None = Field(None, max_length=500)
    input_schema: dict | None = None
    output_schema: dict | None = None


class WorkerHeartbeatRequest(BaseModel):
    """Worker 心跳的请求体（protocol.md §3.3）。"""
    current_load: int = Field(default=0, ge=0)
    current_task_id: str | None = None


class WorkerResponse(AuditFields):
    """Worker 读取操作的响应体。"""
    id: str
    actor_type: str = Field(..., description="human | agent — ADR-004 四实体架构")
    user_id: str | None = Field(None, description="人类 User 的 FK — agent 行为 NULL")
    team_id: str | None = Field(None, description="所属 Team — 人类 Worker 可为 NULL")
    name: str
    provider: str
    provider_model: str | None = None
    status: str
    runtime_status: str | None = None
    last_heartbeat_at: datetime | None = None
    last_progress_at: datetime | None = None
    active_task_id: str | None = None
    capability_tags: dict | None = None
    system_prompt: str | None = None
    metadata: dict | None = None
    batch_size: int = 3
    active_task_count: int = 0
    completed_task_count: int = 0
    active_batches: int = 0

    model_config = {"from_attributes": True}


API_KEY_WARNING = (
    "⚠️ 重要：请妥善保存此 API Key — 仅显示一次，关闭后无法找回。"
)


class WorkerCreateResponse(BaseModel):
    """Worker 创建响应 — 包含明文 API key（仅显示一次）+ 保存警告。"""
    worker: WorkerResponse
    api_key: str = Field(..., description="Plaintext API key — store securely, shown only once")
    warning: str = Field(
        default=API_KEY_WARNING,
        description="API key safety warning — save immediately, shown only once",
    )


class WorkerProjectResponse(BaseModel):
    """Worker 所属 Project 的摘要信息（P11-B9: GET /workers/me/projects）。"""
    project_id: str
    name: str
    display_name: str | None = None
    role: str
    has_project_key: bool = False
