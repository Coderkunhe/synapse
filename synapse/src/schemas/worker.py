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
    # PFL-105 (B106): 自动分配 Project 角色
    project_id: str | None = Field(
        None,
        max_length=40,
        description="Project ID to auto-assign the worker to with the specified role",
    )
    role: str | None = Field(
        None,
        pattern=r"^(builder|orchestrator|steward)$",
        description="Worker role in the project (defaults to 'builder' when project_id is set)",
    )


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
    """Worker 心跳的请求体（protocol.md §3.3）。

    P11-B94: Worker 可上报自己使用的模板版本，Server
    在响应中返回当前版本供 Worker 比对。
    """
    current_load: int = Field(default=0, ge=0)
    current_task_id: str | None = None
    template_version: str | None = Field(
        None,
        description="Worker 当前使用的模板版本 — Server 返回最新版本供比对",
    )


class WorkerHeartbeatResponse(BaseModel):
    """Worker 心跳的响应体（P11-B94 · PFL-084 升级链）。"""
    status: str = Field(..., description="ok | error")
    runtime_status: str | None = Field(None, description="Worker 运行时状态")
    recovery_event: dict | None = Field(None, description="恢复事件（如存在）")
    template_version: str | None = Field(
        None,
        description="Server 当前模板版本 — Worker 应对比自身版本，不一致则需升级",
    )
    role_warnings: list[str] = Field(
        default_factory=list,
        description="角色相关告警 — 如 default_fallback 时提示 Worker 缺少 role 配置",
    )


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
    ws_url: str | None = Field(None, description="WebSocket connection URL (returned during handshake)")

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


class OrchestratorStatusResponse(BaseModel):
    """O 心跳状态 — Builder 启动前检查 O 是否存活（PFL-070 · B87）。

    B92 增强：双源判定 — heartbeat 过期时回退到 Event 活动时间，
    防止心跳 daemon 短暂故障导致误报 offline。
    """

    online: bool = Field(
        ...,
        description="O 是否在线（双源判定：heartbeat 或 event_activity）",
    )
    worker_id: str | None = Field(
        None,
        description="O Worker ID — 无 O 时为 None",
    )
    worker_name: str | None = Field(
        None,
        description="O Worker 名称",
    )
    last_heartbeat_at: datetime | None = Field(
        None,
        description="O 最近心跳时间",
    )
    heartbeat_age_seconds: int | None = Field(
        None,
        description="距上次心跳的秒数 — 无 O 时为 None",
    )
    detection_source: str | None = Field(
        None,
        description="检测来源: heartbeat | event_activity | None（离线）— B92 双源容错",
    )


# ── P12-B5: Worker State Snapshot (Codex sandbox — replace _task-current.md) ──


class TaskStateSummary(BaseModel):
    """Task summary for Worker state snapshot — minimal fields for orientation."""
    id: str
    title: str
    status: str
    owner_id: str | None = None
    owner_name: str | None = None
    owner_type: str | None = None
    priority: str | None = None
    batch_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    created_at: datetime | None = None


class AuthRequestStateSummary(BaseModel):
    """Pending authorization request summary for Worker state snapshot."""
    id: str
    request_type: str
    status: str
    created_at: datetime | None = None
    capability_name: str | None = None


class WorkerStateResponse(BaseModel):
    """P12-B5: Full Worker state snapshot — replaces _task-current.md for
    Codex workers whose sandbox prevents local file writes.

    The Worker AI calls ``GET /v1/workers/me/state?project_id={pid}``
    instead of reading ``_task-current.md``.

    Field semantics match session-init.js's ``state`` object.
    """
    # Identity
    worker_id: str
    worker_name: str
    role: str
    project_id: str
    project_name: str
    runtime_status: str | None = None
    generated_at: datetime

    # Active tasks
    in_progress_tasks: list[TaskStateSummary] = Field(default_factory=list)
    ready_tasks: list[TaskStateSummary] = Field(default_factory=list)
    verification_tasks: list[TaskStateSummary] = Field(default_factory=list)
    all_active_tasks: list[TaskStateSummary] = Field(default_factory=list)
    active_task_count: int = 0

    # Authorization
    pending_auth_requests: list[AuthRequestStateSummary] = Field(default_factory=list)

    # Stale detection
    stale_verification_count: int = 0
    stale_verification_task_ids: list[str] = Field(default_factory=list)

    # Warnings — non-empty when state quality is degraded
    warnings: list[str] = Field(default_factory=list)

    # P14-B2 G1: recent error reports for Builder health visibility
    recent_error_reports: list["ErrorReportSummary"] = Field(default_factory=list)


# ── P14-B2 G1: Error Report schemas ──────────────────────────────────────


class ErrorReportRequest(BaseModel):
    """Builder 结构化错误上报请求体（P14-B2 G1）。

    Builder 通过此端点提交结构化错误上下文，
    替代非结构化的 conversation comment 模式。
    """
    error_type: str = Field(
        ...,
        max_length=50,
        pattern=r"^(api_error|verification_failed|dependency_blocked|capability_mismatch|env_broken|timeout|escalation|unknown)$",
        description="Error category",
    )
    task_id: str | None = Field(
        None,
        max_length=40,
        description="Related task ID (optional — worker-level errors don't need a task)",
    )
    summary: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="One-line error description",
    )
    detail: str | None = Field(
        None,
        max_length=5000,
        description="Full error context (stack trace, API response body, etc.)",
    )
    context: dict | None = Field(
        None,
        description="Structured context (http_status, endpoint, retry_count, etc.)",
    )
    severity: str = Field(
        default="🔴",
        pattern=r"^(🔴|🟡|🟢)$",
        description="Severity: 🔴 critical | 🟡 warning | 🟢 info",
    )


class ErrorReportResponse(BaseModel):
    """Error report 创建响应体（P14-B2 G1）。"""
    id: str
    worker_id: str
    error_type: str
    task_id: str | None = None
    summary: str
    event_id: str
    pfl_id: str | None = None
    escalation_task_id: str | None = None
    severity: str
    created_at: datetime


class ErrorReportSummary(BaseModel):
    """Error report 摘要 — 嵌入 WorkerStateResponse 中。"""
    id: str
    error_type: str
    task_id: str | None = None
    summary: str
    severity: str
    created_at: datetime
