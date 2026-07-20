"""Task schema。"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from src.constants import OwnerType, TaskStatus
from src.schemas.common import AuditFields


class TaskDependency(BaseModel):
    """Task 依赖项（P9-B6）。"""
    task_id: str = Field(..., max_length=40)
    type: str = Field(..., pattern=r"^(sequential|artifact)$")


class TaskCreate(BaseModel):
    """创建 Task 的请求体。"""
    title: str = Field(..., max_length=500)
    description: str = Field(..., min_length=1, max_length=5000)
    priority: str = Field(
        default="p2",
        pattern=r"^(p0|p1|p2|p3)$",
        description="Task priority: p0 (critical), p1 (high), p2 (medium), p3 (low)",
    )
    parent_task_id: str | None = None
    batch_id: str | None = None
    estimated_effort: str | None = Field(
        None,
        pattern=r"^(xs|s|m|l|xl)$",
        description="Estimated effort: xs, s, m, l, or xl (not free-form hours)",
    )
    tags: list[str] | None = None
    metadata: dict | None = None
    deadline_at: datetime | None = None
    # P9-B69: verifications 改为创建时可选，ready 时若无则自动创建默认值
    verifications: list["VerificationCreate"] = Field(default_factory=list)
    # 任务依赖（P9-B6）
    depends_on: list[TaskDependency] | None = None


class BatchTaskCreateRequest(BaseModel):
    """批量创建 Task 的请求体（P8-B9, D-P7-023: Creator 批量操作）。"""
    tasks: list["TaskCreate"] = Field(..., min_length=1, max_length=20)


class TaskUpdate(BaseModel):
    """更新 Task 的请求体。"""
    title: str | None = Field(None, max_length=500)
    description: str | None = None
    priority: str | None = Field(
        None,
        pattern=r"^(p0|p1|p2|p3)$",
        description="Task priority: p0 (critical), p1 (high), p2 (medium), p3 (low)",
    )
    estimated_effort: str | None = Field(
        None,
        pattern=r"^(xs|s|m|l|xl)$",
        description="Estimated effort: xs, s, m, l, or xl (not free-form hours)",
    )
    tags: list[str] | None = None
    metadata: dict | None = None
    deadline_at: datetime | None = None
    expected_version: int = Field(..., ge=1)


class TaskAssignRequest(BaseModel):
    """将 Task 分配给负责人的请求体。"""
    owner_type: OwnerType
    owner_id: str = Field(..., max_length=40)
    expected_version: int = Field(..., ge=1)


class BatchAssignRequest(BaseModel):
    """批量分配多个 Task 的请求体（P8-B3, D-P7-023）。"""
    task_ids: list[str] = Field(..., min_length=1, max_length=20)
    owner_type: OwnerType
    owner_id: str = Field(..., max_length=40)


class BatchClaimResponse(BaseModel):
    """批量领取操作的响应体。"""
    claimed_count: int
    task_ids: list[str]


class BatchReadyRequest(BaseModel):
    """批量将 Task 从 BACKLOG 提升为 READY（P9-B72, S-033）。"""
    task_ids: list[str] = Field(..., min_length=1, max_length=20)


class BatchUpdateRequest(BaseModel):
    """批量更新 Task 字段（P9-B72, S-033）。"""
    task_ids: list[str] = Field(..., min_length=1, max_length=20)
    priority: str | None = Field(
        None,
        pattern=r"^(p0|p1|p2|p3)$",
        description="Task priority: p0 (critical), p1 (high), p2 (medium), p3 (low)",
    )
    estimated_effort: str | None = Field(
        None,
        pattern=r"^(xs|s|m|l|xl)$",
        description="Estimated effort: xs, s, m, l, or xl",
    )
    tags: list[str] | None = None
    deadline_at: datetime | None = None


class BatchOperationError(BaseModel):
    """批量操作中单个 Task 的错误信息。"""
    task_id: str
    error: str


class BatchOperationResponse(BaseModel):
    """批量操作响应体（部分成功模式，P9-B72, S-033）。"""
    updated_count: int
    failed_count: int
    task_ids: list[str]
    errors: list[BatchOperationError] = Field(default_factory=list)


class TaskSubmitRequest(BaseModel):
    """提交 Task 进行验证的请求体（protocol.md §4.4）。"""
    summary: str = Field(..., description="Required. Summary of work completed (what was done, key decisions, etc.)")
    evidence: dict | None = Field(None, description="Optional. JSON object with evidence — PR links, commit hashes, test results, etc. Must be a dict/object, not a plain string.")
    verification_results: list[VerificationResult] = Field(default_factory=list)
    expected_version: int = Field(..., ge=1)


class TaskReadyRequest(BaseModel):
    """将 Task 从 BACKLOG 提升为 READY 的请求体（P9-B63: expected_version 统一到 body）。"""
    expected_version: int = Field(..., ge=1)


class TaskClaimRequest(BaseModel):
    """认领 Task 的请求体（P9-B63: expected_version 统一到 body）。

    expected_version 改为 optional — 缺失时 endpoint 返回引导消息，告诉调用方先 GET task 获取当前版本号。
    """
    expected_version: int | None = Field(default=None, ge=1)


class TaskCancelRequest(BaseModel):
    """取消 Task 的请求体（P9-B63: expected_version 统一到 body）。"""
    expected_version: int = Field(..., ge=1)


class VerificationResult(BaseModel):
    """提交中的单个验证结果。"""
    verification_id: str
    status: str = Field(..., pattern=r"^(passed|failed|approved|rejected)$")
    evidence: str | None = None


class VerificationCreate(BaseModel):
    """嵌入 TaskCreate 的验证条件。"""
    type: str = Field(..., pattern=r"^(manual|automated|check_list)$")
    description: str = Field(..., max_length=1000)
    criteria: dict | None = None


class BlockerReportRequest(BaseModel):
    """Worker 提交阻塞报告的请求体（P8-B7）。"""
    blocker_type: str = Field(..., pattern=r"^(external_dependency|ambiguous_requirements|technical_blocker|other)$")
    description: str = Field(..., max_length=2000)
    suggested_fix: str | None = None
    expected_version: int = Field(..., ge=1)


class TaskTerminateRequest(BaseModel):
    """永久终止 Task 的请求体（P8-B9, I2 基础形式）。"""
    reason: str = Field(..., max_length=2000)
    expected_version: int = Field(..., ge=1)


class TaskResponse(AuditFields):
    """Task 读取操作的响应体。"""
    id: str
    project_id: str
    title: str
    description: str | None = None
    owner_type: OwnerType | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    status: str
    priority: str
    parent_task_id: str | None = None
    batch_id: str | None = None
    estimated_effort: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None
    version_no: int
    deadline_at: datetime | None = None
    completed_at: datetime | None = None
    redo_count: int = 0
    failure_count: int = 0
    failure_reason: str | None = None
    depends_on: list[dict] | None = None
    is_overdue: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_is_overdue(self) -> "TaskResponse":
        """Set is_overdue if deadline has passed and task is still active."""
        if (
            self.deadline_at is not None
            and self.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        ):
            # Convert both to UTC-naive for safe comparison
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            dl = self.deadline_at
            if dl.tzinfo is not None:
                dl = dl.replace(tzinfo=None)
            self.is_overdue = dl < now
        return self
