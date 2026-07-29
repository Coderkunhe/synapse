"""Pydantic schema — API 请求/响应的序列化模型。"""

from src.schemas.common import ActorInfo, AuditFields, CursorPage, ErrorDetail, ErrorResponse
from src.schemas.team import TeamCreate, TeamUpdate, TeamResponse
from src.schemas.member import MemberCreate, MemberUpdate, MemberResponse
from src.schemas.worker import (
    WorkerCreate,
    WorkerUpdate,
    WorkerHandshakeRequest,
    CapabilityDeclaration,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerResponse,
    WorkerCreateResponse,
)
from src.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from src.schemas.task import (
    TaskCreate,
    TaskUpdate,
    TaskAssignRequest,
    TaskSubmitRequest,
    VerificationResult,
    VerificationCreate,
    TaskResponse,
)
from src.schemas.batch import BatchAssignRequest, BatchCreate, BatchUpdate, BatchResponse
from src.schemas.verification import VerificationVerifyRequest, VerificationResponse
from src.schemas.event import EventResponse
from src.schemas.skill import SkillCreate, SkillUpdate, SkillResponse
from src.schemas.protocol import ProtocolResponse
from src.schemas.token_usage import TokenUsageCreate, TokenUsageResponse
from src.schemas.authorization_request import (
    AuthorizationRequestCreate,
    AuthorizationRequestRespond,
    AuthorizationRequestHeartbeat,
    AuthorizationRequestReport,
    AuthorizationRequestResponse,
)
from src.schemas.capability_audit import (
    CapabilityAuditCreate,
    CapabilityAuditListParams,
    CapabilityAuditPage,
    CapabilityAuditResponse,
)
from src.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowRoleAssign,
    WorkflowRoleEntry,
)
from src.schemas.task_worker_conversation import (
    ConversationMessageCreate,
    ConversationMessageUpdate,
    ConversationMessageResponse,
)

# ── Backward compat aliases (P100-B41: Agent→Worker rename) ─────────
AgentCreate = WorkerCreate
AgentUpdate = WorkerUpdate
AgentHandshakeRequest = WorkerHandshakeRequest
AgentHeartbeatRequest = WorkerHeartbeatRequest
AgentResponse = WorkerResponse
AgentCreateResponse = WorkerCreateResponse

__all__ = [
    "ActorInfo",
    "AuditFields",
    "CursorPage",
    "ErrorResponse",
    "ErrorDetail",
    "TeamCreate",
    "TeamUpdate",
    "TeamResponse",
    "MemberCreate",
    "MemberUpdate",
    "MemberResponse",
    # Worker (renamed from Agent, P100-B41)
    "WorkerCreate",
    "WorkerUpdate",
    "WorkerHandshakeRequest",
    "CapabilityDeclaration",
    "WorkerHeartbeatRequest",
    "WorkerHeartbeatResponse",
    "WorkerResponse",
    "WorkerCreateResponse",
    # Backward compat (deprecated, remove after P100-B46)
    "AgentCreate",
    "AgentUpdate",
    "AgentHandshakeRequest",
    "AgentHeartbeatRequest",
    "AgentResponse",
    "AgentCreateResponse",
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectResponse",
    "TaskCreate",
    "TaskUpdate",
    "TaskAssignRequest",
    "TaskSubmitRequest",
    "VerificationResult",
    "VerificationCreate",
    "TaskResponse",
    "BatchAssignRequest",
    "BatchCreate",
    "BatchUpdate",
    "BatchResponse",
    "VerificationVerifyRequest",
    "VerificationResponse",
    "EventResponse",
    "SkillCreate",
    "SkillUpdate",
    "SkillResponse",
    "ProtocolResponse",
    "TokenUsageCreate",
    "TokenUsageResponse",
    # AuthorizationRequest
    "AuthorizationRequestCreate",
    "AuthorizationRequestRespond",
    "AuthorizationRequestHeartbeat",
    "AuthorizationRequestReport",
    "AuthorizationRequestResponse",
    # CapabilityAudit (P11-B57)
    "CapabilityAuditListParams",
    "CapabilityAuditPage",
    "CapabilityAuditResponse",
    # Workflow + WorkflowRole
    "WorkflowCreate",
    "WorkflowUpdate",
    "WorkflowResponse",
    "WorkflowRoleAssign",
    "WorkflowRoleEntry",
    # TaskWorkerConversation (A2A)
    "ConversationMessageCreate",
    "ConversationMessageUpdate",
    "ConversationMessageResponse",
]
