"""Custom exception classes and FastAPI exception handlers.

Error format follows protocol.md §9:
  {"error": {"code": "...", "message": "...", "details": {...}}, "requestId": "..."}
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class SynapseError(Exception):
    """Base exception with structured error response fields."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class InvalidStateTransition(SynapseError):
    """Raised when a state machine transition is not allowed."""

    def __init__(self, entity_type: str, entity_id: str, from_status: str, to_status: str):
        super().__init__(
            status_code=400,
            code="INVALID_STATUS_TRANSITION",
            message=f"Cannot transition {entity_type} {entity_id} from '{from_status}' to '{to_status}'",
            details={
                "entityType": entity_type,
                "entityId": entity_id,
                "from": from_status,
                "to": to_status,
            },
        )


class NotFoundError(SynapseError):
    """Raised when a requested entity does not exist."""

    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(
            status_code=404,
            code=f"NOT_FOUND_{entity_type.upper()}",
            message=f"{entity_type} not found: {entity_id}",
            details={"entityType": entity_type, "entityId": entity_id},
        )


class ForbiddenError(SynapseError):
    """Raised when the actor lacks permission for an operation."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(
            status_code=403,
            code=code,
            message=message,
            details=details,
        )


class ConflictError(SynapseError):
    """Raised when an operation conflicts with current state."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(
            status_code=409,
            code=code,
            message=message,
            details=details,
        )


class AuthenticationError(SynapseError):
    """Raised when authentication fails (missing/invalid token or API key)."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(
            status_code=401,
            code=code,
            message=message,
            details=details,
        )


class AuthorizationPendingError(SynapseError):
    """Raised when a Worker needs project authorization — an api_auth
    AuthorizationRequest has been created and the Worker should poll for
    the approval result before retrying the original operation.

    P10-B31: S-065 403 拦截器 — Worker 遇 403 后系统自动创建
    api_auth 请求，返回 202 让 Worker 进入 poll 模式。
    """

    def __init__(
        self,
        authorization_request_id: str,
        message: str = "Authorization required. Poll the authorization request for status.",
        details: dict | None = None,
    ):
        super().__init__(
            status_code=202,
            code="AUTHORIZATION_PENDING",
            message=message,
            details={
                "authorization_request_id": authorization_request_id,
                **(details or {}),
            },
        )
        self.authorization_request_id = authorization_request_id


# --- FastAPI exception handlers ---

async def synapse_error_handler(request: Request, exc: SynapseError) -> JSONResponse:
    """Convert SynapseError to structured JSON error response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        },
    )
