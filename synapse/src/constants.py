"""Synapse 领域类型的规范枚举定义。

所有枚举使用 Python 3.11+ StrEnum，因此成员是直接的 str 子类：
    TaskStatus.BACKLOG == "backlog"  # True
    WorkerStatus.ACTIVE in ("pending", "active")  # True

这意味着无需迁移 — SQLAlchemy 中现有的 String 列直接接受这些值。
"""

from __future__ import annotations

from enum import StrEnum


# ── 分页默认值 ────────────────────────────────────────────────────────────
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100

# ── 授权请求流控 ────────────────────────────────────────────────────────────
MAX_PENDING_AUTH_REQUESTS = 5
"""单个 Worker 最多同时有 5 个 pending 授权请求。"""


# ── 状态枚举 ────────────────────────────────────────────────────────────

class WorkerActorType(StrEnum):
    """Worker 的执行者类型 — 人还是 AI。

    ADR-004 四实体架构：同一张 workers 表，人类和 AI 统一建模。
    ``actor_type`` 驱动 UI 分层渲染（人类优先、同表不同卡）。
    """

    HUMAN = "human"
    AGENT = "agent"


class WorkerStatus(StrEnum):
    """已注册 Worker 的生命周期状态（注册→激活→退役）。"""

    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"




class WorkerRuntimeStatus(StrEnum):
    """活跃 Worker 的运行时状态 — 驱动运行时状态机。

    生命周期：IDLE → BUSY → ERROR → IDLE（恢复）。
    只有 ``WorkerStatus.ACTIVE`` 的 Worker 参与运行时池。
    """

    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"




class TaskStatus(StrEnum):
    """Task 的工作流状态 — 驱动 Task.ALLOWED_TRANSITIONS 中的状态机。

    生命周期：BACKLOG → READY → IN_PROGRESS → IN_VERIFICATION → COMPLETED
                                            ↓ PAUSED    ↓ REJECTED（→ IN_PROGRESS 重做）
                                            ↓ CANCELLED（终态，任意预终态均可取消）
    """

    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    IN_VERIFICATION = "in_verification"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class VerificationStatus(StrEnum):
    """单次 Verification 检查的结果状态。"""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ProjectStatus(StrEnum):
    """Project 的生命周期状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class BatchStatus(StrEnum):
    """Batch（任务包）的生命周期状态 — 对齐 data-model.md §3.7 状态机。"""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkflowStatus(StrEnum):
    """Workflow 的生命周期状态。

    P10-B24: 议题 4 per-Workflow 角色 — Workflow 实体首次引入。
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ── 角色枚举 ───────────────────────────────────────────────────────────

class ProjectRole(StrEnum):
    """Project 内角色 — 统一三套独立角色系统。

    P10-B24: 议题 4 per-Workflow 角色 — 首次引入统一角色枚举。

    **管理权限**（ProjectActorRole 用）：
    - ADMIN / LEAD / MEMBER

    **Workflow 内职能**（WorkflowRole 用）：
    - ORCHESTRATOR / BUILDER / STEWARD（P10 模型支持，功能暂不暴露）
    """

    # ── Project 管理权限 ──
    ADMIN = "admin"
    LEAD = "lead"
    MEMBER = "member"
    # ── Workflow 内职能 ──
    ORCHESTRATOR = "orchestrator"
    BUILDER = "builder"
    STEWARD = "steward"  # P10 模型支持，功能暂不暴露（D-P10-004）


# ── 类型/分类枚举 ───────────────────────────────────────────────────────

class EventType(StrEnum):
    """写入 Event 账本的规范事件类型。

    命名约定：``{entity}.{action}``。
    """

    # Worker lifecycle (primary names — S-016)
    WORKER_REGISTERED = "worker.registered"
    WORKER_HANDSHAKE = "worker.handshake"
    WORKER_DEACTIVATED = "worker.deactivated"
    WORKER_HEARTBEAT = "worker.heartbeat"
    WORKER_RUNTIME_IDLE = "worker.runtime.idle"
    WORKER_RUNTIME_BUSY = "worker.runtime.busy"
    WORKER_RUNTIME_ERROR = "worker.runtime.error"

    # Worker project role (P10-B18)
    WORKER_PROJECT_ROLE_ASSIGNED = "worker.project_role.assigned"
    WORKER_PROJECT_ROLE_CHANGED = "worker.project_role.changed"
    WORKER_PROJECT_ROLE_REVOKED = "worker.project_role.revoked"

    # Batch lifecycle
    BATCH_CREATED = "batch.created"
    BATCH_COMPLETED = "batch.completed"              # P8-B9: all tasks terminal

    # Member lifecycle
    MEMBER_INVITED = "member.invited"
    MEMBER_REMOVED = "member.removed"

    # Project lifecycle
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_ARCHIVED = "project.archived"

    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_READIED = "task.readied"
    TASK_ASSIGNED = "task.assigned"
    TASK_CLAIMED = "task.claimed"
    TASK_SUBMITTED = "task.submitted"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"
    TASK_COMPLETED = "task.completed"
    TASK_REJECTED = "task.rejected"
    TASK_CANCELLED = "task.cancelled"
    TASK_LEASE_EXPIRED = "task.lease_expired"
    TASK_BLOCKER_REPORTED = "task.blocker_reported"    # P8-B7
    TASK_REVIEW_TIMEOUT = "task.review_timeout"        # P8-B7
    REVIEW_OVERDUE = "review.overdue"                  # P8-B9: WS signal for review timeout
    TASK_ESCALATED = "task.escalated"                  # P8-B7

    # Team lifecycle
    TEAM_CREATED = "team.created"
    TEAM_UPDATED = "team.updated"

    # Analysis
    ANALYSIS_CREATED = "analysis.created"

    # Scan
    SCAN_EXECUTED = "scan.executed"

    # Skill
    SKILL_CREATED = "skill.created"
    SKILL_UPDATED = "skill.updated"
    SKILL_DEPRECATED = "skill.deprecated"

    # Verification
    VERIFICATION_CREATED = "verification.created"       # P11-B106: creation endpoint + auto-create
    VERIFICATION_EXECUTED = "verification.executed"
    VERIFICATION_RESET = "verification.reset"           # P8-B8: rework re-submission

    # AuthorizationRequest (P10-B21)
    AUTHORIZATION_REQUEST_CREATED = "authorization_request.created"
    AUTHORIZATION_REQUEST_RESPONDED = "authorization_request.responded"
    AUTHORIZATION_REQUEST_EXPIRED = "authorization_request.expired"
    AUTHORIZATION_REQUEST_CANCELLED = "authorization_request.cancelled"
    AUTHORIZATION_REQUEST_HEARTBEAT = "authorization_request.heartbeat"
    AUTHORIZATION_REQUEST_EXECUTED = "authorization_request.executed"  # P11-B46: capability execution reported

    # Workflow lifecycle (P10-B24)
    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_UPDATED = "workflow.updated"
    WORKFLOW_COMPLETED = "workflow.completed"

    # Workflow role (P10-B24)
    WORKFLOW_ROLE_ASSIGNED = "workflow_role.assigned"
    WORKFLOW_ROLE_CHANGED = "workflow_role.changed"
    WORKFLOW_ROLE_REVOKED = "workflow_role.revoked"

    # A2A Conversation (P10-B28)
    CONVERSATION_MESSAGE_CREATED = "conversation.message.created"
    CONVERSATION_MESSAGE_RESOLVED = "conversation.message.resolved"

    # Protection Report (P10-B35)
    PROTECTION_REPORT_CREATED = "protection_report.created"
    PROTECTION_REPORT_COMPLETED = "protection_report.completed"

    # Circuit Breaker (P10-B35)
    CIRCUIT_BREAKER_OPENED = "circuit_breaker.opened"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker.closed"

    # Decision Audit (P10-B35)
    DECISION_AUDIT_RECORDED = "decision_audit.recorded"


class ActorType(StrEnum):
    """存储在 Event.actor_type 中的多态参与者类型。"""

    WORKER = "worker"
    HUMAN = "human"   # P10-B8: was "member" — ADR-004 人类统一建模为 Worker
    SYSTEM = "system"


class VerificationType(StrEnum):
    """Verification 检查的分类。"""

    MANUAL = "manual"
    AUTOMATED = "automated"
    CHECK_LIST = "check_list"


class OwnerType(StrEnum):
    """存储在 Task.owner_type 中的多态所有者类型。"""

    MEMBER = "member"
    WORKER = "worker"


class SkillStatus(StrEnum):
    """Skill 定义的生命周期状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


class ScanTarget(StrEnum):
    """ComplianceScan 的目标实体类型。

    MVP 中仅 ``task`` 和 ``batch`` 活跃；``skill`` 和 ``worker``
    为预留（宽数据结构 + 薄实现）。
    """

    TASK = "task"
    BATCH = "batch"
    SKILL = "skill"      # reserved — awaiting Skills model
    WORKER = "worker"    # reserved


class ScanVerdictStatus(StrEnum):
    """ComplianceScan 规则的判定结果状态。"""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


# ── 认证错误码 ────────────────────────────────────────────────────────────


class AuthErrorCode(StrEnum):
    """认证相关错误码 — email/password 注册和登录。"""

    EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    INVALID_EMAIL = "INVALID_EMAIL"
    RESET_TOKEN_EXPIRED = "RESET_TOKEN_EXPIRED"
    RESET_TOKEN_ALREADY_USED = "RESET_TOKEN_ALREADY_USED"
    INVALID_RESET_TOKEN = "INVALID_RESET_TOKEN"


# ── 认证限流常量 ───────────────────────────────────────────────────────────

AUTH_RATE_LIMIT_LOGIN = "5/minute"
"""登录端点每 IP 限流（5 次/分钟）。"""

AUTH_RATE_LIMIT_REGISTER = "3/minute"
"""注册端点每 IP 限流（3 次/分钟）。"""


# ── 分析类型枚举 ───────────────────────────────────────────────────────────


class AnalysisType(StrEnum):
    """分析记录的类型 — 分类所执行的分析类型。

    MVP 中前 3 个值活跃；其余 3 个为预留（宽数据结构 + 薄实现）。
    """

    REQUIREMENT = "requirement"
    DISCUSSION = "discussion"
    DESIGN = "design"
    RISK_ASSESSMENT = "risk_assessment"
    DEPENDENCY_MAP = "dependency_map"
    RETROSPECTIVE = "retrospective"


# ── A2A 通信枚举 ─────────────────────────────────────────────────────────


class ConversationMessageType(StrEnum):
    """A2A 结构化消息类型 — TaskWorkerConversation 的消息分类。

    P10-B28: 议题 5 A2A 协议 — 数据基础层。
    """

    CLARIFICATION = "clarification"
    """澄清问题 — Worker 对任务需求有疑问，需要 Orchestrator 或其他 Worker 澄清。"""

    BLOCKING = "blocking"
    """阻塞信号 — Worker 遇到阻塞依赖，无法继续执行，需外部解除。"""

    REVIEW_REQUEST = "review_request"
    """请求审查 — Worker 完成阶段性工作，请求 Peer Review 或 Orchestrator 验收。"""

    HANDOFF = "handoff"
    """任务交接 — Worker 主动将任务转交给另一个 Worker，触发 task.assign AuthorizationRequest。"""


# ── 保护报告 + 熔断 + 决策审计 ─────────────────────────────────────────

class ProtectionReportType(StrEnum):
    """保护报告类型 — 三种检测模式。

    P10-B35: 议题 ⑥ 保护报告+熔断+决策审计 — 数据基础层。
    """

    CROSS_PROJECT_ACCESS = "cross_project_access"
    """跨 Project 访问检测 — Worker 在多个 Project 间的资源访问模式异常。"""

    SENSITIVE_WORKER_OVERLAP = "sensitive_overlap"
    """敏感 Worker 重叠 — 具有敏感能力的 Worker 在多个 Project 中重叠。"""

    CAPABILITY_DRIFT = "capability_drift"
    """能力漂移 — Worker 的能力声明随时间变化，检测异常漂移。"""


class ProtectionReportStatus(StrEnum):
    """保护报告的生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CircuitBreakerTargetType(StrEnum):
    """熔断器目标类型 — worker 级或 project 级熔断。"""

    WORKER = "worker"
    PROJECT = "project"


class CircuitBreakerStateEnum(StrEnum):
    """熔断器状态 — 标准三段式熔断状态机。

    CLOSED → (failures ≥ threshold) → OPEN → (cooldown elapsed) → HALF_OPEN
    → (success) → CLOSED 或 (failure) → OPEN
    """

    CLOSED = "closed"
    """正常状态 — 允许所有操作。"""

    OPEN = "open"
    """熔断状态 — 拒绝所有操作，直到冷却期结束。"""

    HALF_OPEN = "half_open"
    """半开状态 — 允许有限试探操作，成功则关闭熔断，失败则重新打开。"""


class DecisionType(StrEnum):
    """决策审计类型 — 授权决策的分类。"""

    APPROVE = "approve"
    DENY = "deny"
    EXPIRE = "expire"
    CANCEL = "cancel"
    AUTO_GRANT = "auto_grant"


class RiskLevel(StrEnum):
    """决策风险等级 — 决策时评估的风险级别。

    为远期信任分（trust score）提供数据基础。
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
