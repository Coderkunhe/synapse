"""Workflow + WorkflowRole schema。

P10-B25: 议题 4 per-Workflow 角色 — Schemas 层。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.constants import ProjectRole, WorkflowStatus
from src.schemas.common import AuditFields


# ── Workflow CRUD schemas ──────────────────────────────────────────


class WorkflowCreate(BaseModel):
    """创建 Workflow 的请求体。"""

    name: str = Field(..., max_length=200, description="Workflow 名称")
    description: str | None = Field(None, description="Workflow 目标描述")
    status: str = Field(
        default=WorkflowStatus.ACTIVE,
        description="初始状态，默认 active",
    )


class WorkflowUpdate(BaseModel):
    """更新 Workflow 的请求体（所有字段可选）。"""

    name: str | None = Field(None, max_length=200)
    description: str | None = None
    status: str | None = None


class WorkflowResponse(AuditFields):
    """Workflow 读取操作的响应体。"""

    id: str
    project_id: str
    name: str
    description: str | None = None
    status: str


# ── WorkflowRole schemas ───────────────────────────────────────────


class WorkflowRoleAssign(BaseModel):
    """为 Worker 在 Workflow 中分配角色的请求体。"""

    worker_id: str = Field(..., description="Worker ID（人或 AI）")
    role: str = Field(..., description="Workflow 内职能 — orchestrator | builder (P10) | steward (预留)")


class WorkflowRoleEntry(AuditFields):
    """WorkflowRole 单条记录（用于列表响应）。"""

    id: str
    workflow_id: str
    worker_id: str
    role: str
