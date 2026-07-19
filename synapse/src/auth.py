"""Authentication: JWT verification for Members and API Key verification for Workers."""

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Header, Request
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.constants import ActorType, WorkerStatus
from src.exceptions import AuthenticationError
from src.utils.id_gen import PREFIXES


# --- JWT (Actor auth — human Workers via OAuth) ---

def create_access_token(
    user_id: str,
    team_id: str,
    role: str,
    *,
    actor_id: str | None = None,
    member_id: str | None = None,  # deprecated — use actor_id
    actor_type: str = ActorType.HUMAN,  # P10-B8: ADR-004 统一 — humans → Worker with actor_type="human"
    is_super_admin: bool = False,  # P10-B17: DB 宽列首用 — 超管标记入 JWT
) -> str:
    """Create a JWT access token for an authenticated actor.

    The ``sub`` claim holds the user_id (stable across teams), while
    ``actorId`` identifies the specific actor (worker_id for human Workers,
    derived deterministically from member_id).

    P10-B7: ``actor_id`` replaces ``member_id`` as the primary identifer.
    The deprecated ``member_id`` kwarg is accepted as a fallback.
    P10-B8: ``actor_type`` is now ``"human"`` (was ``"member"``) — aligned
    with ``WorkerActorType.HUMAN`` per ADR-004.
    P10-B17: ``is_super_admin`` added to JWT payload — enables super-admin
    bypass of role-based permission checks.
    """
    effective_actor_id = actor_id or member_id
    if not effective_actor_id:
        raise ValueError("actor_id is required")

    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "actorId": effective_actor_id,
        "teamId": team_id,
        "role": role,
        "actor_type": actor_type,
        "is_super_admin": is_super_admin,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token. Raises AuthenticationError on failure."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        raise AuthenticationError("AUTH_INVALID_TOKEN", "Invalid or expired access token")


# --- Token hashing and generation utilities ---


def hash_token(token: str) -> str:
    """SHA-256 hash a token value for storage. Never store plaintext tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token_value() -> str:
    """Generate an opaque refresh token string (64 hex chars, 256-bit entropy)."""
    import secrets

    return secrets.token_hex(32)


def create_user_id(oauth_provider: str, oauth_subject: str) -> str:
    """Derive a consistent user_id from OAuth identity.

    Format: ``usr_{sha256(provider:subject)[:16]}``.
    The same (provider, subject) pair always produces the same user_id.
    Delegates to :func:`src.utils.id_gen.derive_id` for canonical prefix.
    """
    from src.utils.id_gen import derive_id

    return derive_id(f"{oauth_provider}:{oauth_subject}", "user")


# --- API Key (Worker auth) ---

def hash_api_key(api_key: str) -> str:
    """SHA-256 hash an API key for storage. Keys are never stored in plaintext."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key(worker_id: str) -> tuple[str, str]:
    """Generate a new API key and its hash.

    Returns:
        (plaintext_key, hashed_key). The plaintext is returned ONCE at creation.
    """
    import secrets

    random_part = secrets.token_hex(32)
    worker_prefix = worker_id.replace(f"{PREFIXES['worker']}_", "")[:8]
    plaintext = f"{settings.api_key_prefix}{random_part}.{worker_prefix}"
    hashed = hash_api_key(plaintext)
    return plaintext, hashed


async def verify_api_key(api_key: str, db: AsyncSession) -> dict | None:
    """Verify an API key against stored hashes. Returns worker info dict or None.

    P11-B8: Accepts PENDING workers (in addition to ACTIVE).
    Previously only ACTIVE workers could pass — but new workers are PENDING
    until handshake, creating a chicken-and-egg: they need a valid session
    to handshake, but their key is rejected before handshake.
    Endpoints that truly require ACTIVE (e.g. task claim) should add their
    own status check, not rely on the auth layer.
    """
    from src.models.worker import Worker

    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(Worker).where(Worker.api_key_hash == key_hash)
    )
    worker = result.scalar_one_or_none()

    if worker is None:
        return None
    if worker.status not in (WorkerStatus.PENDING, WorkerStatus.ACTIVE):
        return None

    return {
        "actor_id": worker.id,
        "team_id": worker.team_id,
        "actor_type": ActorType.WORKER,
        "name": worker.name,
    }


# --- Project Key (P11-B8: project-level access credential) ---


def hash_project_key(project_key: str) -> str:
    """SHA-256 hash a project key for storage. Keys are never stored in plaintext."""
    return hashlib.sha256(project_key.encode()).hexdigest()


def generate_project_key(project_id: str) -> tuple[str, str]:
    """Generate a new project key and its hash.

    Project keys are unguessable secrets used by Workers to discover and
    access specific projects. Analogous to API keys but scoped to a project
    rather than a worker.

    Format: ``spk_{64_hex_chars}.{project_id_prefix}``

    Returns:
        (plaintext_key, hashed_key). The plaintext is returned ONCE at creation.
    """
    import secrets

    random_part = secrets.token_hex(32)
    project_prefix = project_id.replace("prj_", "")[:8]
    plaintext = f"{settings.project_key_prefix}{random_part}.{project_prefix}"
    hashed = hash_project_key(plaintext)
    return plaintext, hashed


# --- Token extraction from request ---

async def extract_bearer_token(request: Request) -> str | None:
    """Extract Bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None
