"""Task schema。"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

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
    required_capabilities: list[str] | None = None
    metadata: dict | None = None
    deadline_at: datetime | None = None
    # P9-B69: verifications 改为创建时可选，ready 时若无则自动创建默认值
    verifications: list["VerificationCreate"] = Field(default_factory=list)
    # 任务依赖（P9-B6）
    depends_on: list[TaskDependency] | None = None

    @field_validator("description")
    @classmethod
    def normalize_description(cls, v: str) -> str:
        """FR3: 规范化 description — \r\n→\n · strip 首尾空白 · 保留合法 JSON 换行。"""
        if v is None:
            return v
        return v.replace("\r\n", "\n").replace("\r", "\n").strip()


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
    required_capabilities: list[str] | None = None
    metadata: dict | None = None
    deadline_at: datetime | None = None
    expected_version: int = Field(..., ge=1)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, v: str | None) -> str | None:
        """FR3: 规范化 description — \r\n→\n · strip 首尾空白。"""
        if v is None:
            return None
        return v.replace("\r\n", "\n").replace("\r", "\n").strip()


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
    required_capabilities: list[str] | None = None
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
    evidence: dict | None = Field(None, description="Required. JSON object with evidence — PR links, commit hashes, test results, etc. Must be a dict/object, not a plain string. PFL-143: empty/null evidence rejected at submit.")
    verification_results: list[VerificationResult] = Field(default_factory=list)
    expected_version: int = Field(..., ge=1)

    @field_validator("evidence")
    @classmethod
    def check_evidence_non_empty(cls, v: dict | None) -> dict:
        """PFL-143: Reject null or empty evidence at submit time.

        Codex CLI was observed submitting with evidence field that didn't
        match Server format — Server accepted the submit but discarded the
        evidence silently.  This validator forces the Builder to provide
        evidence before submit can succeed, and the error message tells
        them the expected format.
        """
        if v is None or len(v) == 0:
            raise ValueError(
                "evidence is required and must be a non-empty JSON object. "
                "Expected format: {'key': 'value', ...} with at minimum an "
                "'output_access' field. See SKILL.md §逐项 Evidence 协议."
            )
        return v


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


# ── P11-B70: expected_evidence_type 枚举 ─────────────────────
EXPECTED_EVIDENCE_TYPES: set[str] = {
    "command_output",   # 命令执行输出（测试、lint、脚本）
    "artifact_hash",    # 产物文件（路径 + SHA256 + 大小）
    "api_response",     # API 响应（状态码 + 关键字段）
    "external_ref",     # 外部系统引用（Git commit, CI run ID）
    "self_report",      # 自我声明（仅限主观判断类条件）
}
VAGUE_DESCRIPTIONS: set[str] = {
    "代码写好了", "功能正常", "没问题", "做好了", "完成了",
    "code is done", "works fine", "looks good", "done",
    "测试通过", "lint过了", "没问题了", "it works",
    "差不多", "还行", "ok", "好了",
}


class VerificationCreate(BaseModel):
    """嵌入 TaskCreate 的验证条件。

    P11-B70: 新增 expected_evidence_type 字段 + 可判定性 validator。
    """
    type: str = Field(..., pattern=r"^(manual|automated|check_list)$")
    description: str = Field(..., max_length=1000)
    criteria: dict | None = None
    expected_evidence_type: str | None = Field(
        None,
        description=(
            "Expected evidence type for this verification. "
            "One of: command_output, artifact_hash, api_response, external_ref, self_report. "
            "Builder must provide evidence matching this type."
        ),
    )

    @field_validator("description")
    @classmethod
    def check_decidability(cls, v: str) -> str:
        """P11-B70: 拒绝模糊的 Verification 描述。

        "代码写好了"、"功能正常" 这类模糊措辞在 Task 创建阶段就被拦截，
        不等 Builder 开始干活才发现验收标准不可判定。
        """
        stripped = v.strip()
        if len(stripped) < 6:
            raise ValueError(
                f"Verification description too short ({len(stripped)} chars): '{stripped}'. "
                f"Must be ≥6 characters with specific, machine-verifiable criteria. "
                f"Example: 'pytest 23/23 passed, ruff 0 errors'"
            )
        if stripped.lower() in VAGUE_DESCRIPTIONS:
            raise ValueError(
                f"Verification description too vague: '{stripped}'. "
                f"Use specific criteria with measurable indicators. "
                f"Example: 'POST /login returns 200 + response contains access_token + test_auth.py 12/12 passed'"
            )
        return stripped

    @field_validator("expected_evidence_type")
    @classmethod
    def check_evidence_type(cls, v: str | None) -> str | None:
        if v is not None and v not in EXPECTED_EVIDENCE_TYPES:
            raise ValueError(
                f"Invalid expected_evidence_type: '{v}'. "
                f"Must be one of: {', '.join(sorted(EXPECTED_EVIDENCE_TYPES))}"
            )
        return v


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
    required_capabilities: list[str] | None = None
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


# ── P12-B43: Dependency chain ──────────────────────────────────────


class DependencyChainItem(BaseModel):
    """A single node in a dependency chain — summary of a related task."""

    task_id: str
    title: str
    status: str
    dependency_type: str = "sequential"


class DependencyChain(BaseModel):
    """Upstream + downstream dependency chains."""

    upstream: list[DependencyChainItem] = Field(default_factory=list)
    downstream: list[DependencyChainItem] = Field(default_factory=list)


class DependencyChainView(BaseModel):
    """Full recursive dependency chain for a single task (computed, not DB-backed)."""

    task_id: str
    chain: DependencyChain
