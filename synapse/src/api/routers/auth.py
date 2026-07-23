"""OAuth authentication endpoints.

Endpoints
    GET  /v1/auth/oauth/github           — initiate GitHub OAuth (redirect)
    GET  /v1/auth/oauth/github/callback  — handle GitHub callback
    POST /v1/auth/register               — email/password registration
    POST /v1/auth/login                  — email/password login
    POST /v1/auth/forgot-password        — request password reset
    POST /v1/auth/reset-password         — reset password with token
    POST /v1/auth/refresh                — refresh access token (cookie-based)
    POST /v1/auth/logout                 — logout (revoke refresh token)
    GET  /v1/auth/me                     — current auth status
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import create_access_token
from src.config import settings
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import AuthenticationError
from src.models.member import Member
from src.models.user import User
from src.schemas.auth import (
    AuthStatusResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from src.services.auth_service import (
    complete_password_reset,
    create_refresh_token_record,
    exchange_github_code,
    generate_pkce_pair,
    get_github_authorize_url,
    get_github_user,
    initiate_password_reset,
    login_user,
    register_user,
    revoke_refresh_token,
    upsert_member_via_oauth,
    verify_and_rotate_refresh_token,
)
from src.utils.id_gen import derive_id

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Cookie config ─────────────────────────────────────────────────────────────

COOKIE_KEY = "refresh_token"
COOKIE_PATH = "/v1/auth"
COOKIE_MAX_AGE = settings.refresh_token_expire_days * 86400
OAUTH_STATE_MAX_AGE = 600  # 10 minutes


def _set_refresh_cookie(response: Response, token_value: str) -> None:
    """Set the refresh token as an httpOnly cookie."""
    response.set_cookie(
        key=COOKIE_KEY,
        value=token_value,
        max_age=COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
    )


def _set_access_cookie(response: Response, token_value: str) -> None:
    """Set the access token as an httpOnly cookie."""
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=token_value,
        max_age=settings.jwt_expire_minutes * 60,
        path="/v1",
        httponly=True,
        secure=settings.cookie_secure and not settings.debug,
        samesite="lax",
    )


def _clear_access_cookie(response: Response) -> None:
    """Remove the access token cookie."""
    response.delete_cookie(key=settings.access_token_cookie_name, path="/v1")


def _clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh token cookie."""
    response.delete_cookie(key=COOKIE_KEY, path=COOKIE_PATH)


# ── Dev login (debug only) ─────────────────────────────────────────────────────


@router.get("/dev-token")
async def dev_token(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a dev JWT token. Only available in debug mode."""
    if not settings.debug:
        raise AuthenticationError("AUTH_FORBIDDEN", "Dev token only in debug mode")

    from src.models.team import Team
    from src.utils.id_gen import generate_id

    team_result = await db.execute(select(Team).limit(1))
    team = team_result.scalar_one_or_none()
    if team is None:
        team = Team(id=generate_id("team"), name="Dev Team", slug="dev-team")
        db.add(team)
        await db.flush()

    member_result = await db.execute(
        select(Member).where(
            Member.oauth_provider == "dev",
            Member.team_id == team.id,
        ).limit(1)
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        member = Member(
            id=generate_id("member"),
            team_id=team.id,
            user_id="dev-admin",
            display_name="Dev Admin",
            role="admin",
            oauth_provider="dev",
            oauth_subject="dev-admin",
        )
        db.add(member)
        await db.flush()
        await db.commit()

    worker_id = derive_id(member.id, "worker")
    access_token = create_access_token(
        user_id=member.user_id,
        actor_id=worker_id,
        team_id=member.team_id,
        role=member.role,
        is_super_admin=True,  # P10-B17: dev admin is super-admin
    )
    response = JSONResponse({
        "access_token": access_token,
        "actor_id": worker_id,
        "member_id": member.id,
        "team_id": member.team_id,
        "role": member.role,
        "display_name": member.display_name or "Dev Admin",
        "expires_in": settings.jwt_expire_minutes * 60,
        "is_super_admin": True,
        "force_password_change": False,
        "user_id": member.user_id,
    })
    _set_access_cookie(response, access_token)
    return response


# ── Email/Password endpoints ──────────────────────────────────────────────────


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Register a new user with email and password.

    Creates a User, UserAuthMethod (provider="email"), human Worker,
    and issues JWT + refresh token. The refresh token is set as an httpOnly
    cookie for browser clients.
    """
    user, worker_id, access_token, refresh_token_value = await register_user(
        db,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    await db.commit()

    content = TokenResponse(
        access_token=access_token,
        actor_id=worker_id,
        member_id="",  # email/password auth has no Member yet
        team_id="",
        role="",
        display_name=user.display_name,
        expires_in=settings.jwt_expire_minutes * 60,
        is_super_admin=user.is_super_admin,
        force_password_change=user.force_password_change,
        user_id=user.id,
    ).model_dump()

    response = JSONResponse(content=content, status_code=201)
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token_value)
    return response


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Login with email and password.

    Verifies credentials, issues JWT + refresh token. The refresh token
    is set as an httpOnly cookie for browser clients.
    """
    user, worker_id, access_token, refresh_token_value, team_role = await login_user(
        db,
        email=body.email,
        password=body.password,
    )
    team_id, role, member_id = team_role
    await db.commit()

    content = TokenResponse(
        access_token=access_token,
        actor_id=worker_id,
        member_id=member_id,
        team_id=team_id,
        role=role,
        display_name=user.display_name,
        expires_in=settings.jwt_expire_minutes * 60,
        is_super_admin=user.is_super_admin,
        force_password_change=user.force_password_change,
        user_id=user.id,
    ).model_dump()

    response = JSONResponse(content=content)
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token_value)
    return response


# ── Password Reset endpoints ──────────────────────────────────────────────────


@router.post("/forgot-password", status_code=200)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request a password reset link.

    Always returns 200 with the same message whether or not the email
    is registered — prevents user enumeration attacks.

    SMTP configured: token sent via email, not in response.
    SMTP not configured: token returned in response (dev/test/airgap).
    """
    reset_token = await initiate_password_reset(db, email=body.email)
    await db.commit()

    response: dict = {
        "message": "If the email is registered, a reset link has been sent",
    }
    if reset_token:
        response["reset_token"] = reset_token
    return response


@router.post("/reset-password", status_code=200)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reset password using a reset token.

    Verifies the token, updates the user's password, and marks the
    token as used (non-reusable).
    """
    await complete_password_reset(
        db,
        token=body.token,
        new_password=body.new_password,
    )
    await db.commit()
    return {"message": "Password has been reset"}


# ── OAuth endpoints ───────────────────────────────────────────────────────────


@router.get("/oauth/github")
async def oauth_github_authorize() -> RedirectResponse:
    """Initiate GitHub OAuth flow with PKCE."""
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    auth_url = get_github_authorize_url(code_challenge, state)

    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key="oauth_code_verifier",
        value=code_verifier,
        max_age=OAUTH_STATE_MAX_AGE,
        path=COOKIE_PATH,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
    )
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=OAUTH_STATE_MAX_AGE,
        path=COOKIE_PATH,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
    )
    return response


@router.get("/oauth/github/callback")
async def oauth_github_callback(
    request: Request,
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle GitHub OAuth callback — exchange code, upsert member, issue tokens."""
    # Validate state (CSRF protection)
    expected_state = request.cookies.get("oauth_state", "")
    if not expected_state or not secrets.compare_digest(expected_state, state):
        return RedirectResponse(
            url=f"{settings.frontend_url}/login?error=invalid_state", status_code=302
        )

    # Retrieve PKCE verifier
    code_verifier = request.cookies.get("oauth_code_verifier", "")
    if not code_verifier:
        return RedirectResponse(
            url=f"{settings.frontend_url}/login?error=missing_verifier", status_code=302
        )

    # Exchange code for GitHub access token
    github_token = await exchange_github_code(code, code_verifier)

    # Fetch GitHub user profile
    gh_user = await get_github_user(github_token)

    # Upsert member
    member = await upsert_member_via_oauth(
        db,
        oauth_provider=gh_user["provider"],
        oauth_subject=gh_user["subject"],
        email=gh_user["email"],
        display_name=gh_user["display_name"],
        avatar_url=gh_user["avatar_url"],
    )
    await db.flush()

    # Issue tokens
    worker_id = derive_id(member.id, "worker")
    access_token = create_access_token(
        user_id=member.user_id,
        actor_id=worker_id,
        team_id=member.team_id,
        role=member.role,
    )
    refresh_token_value = await create_refresh_token_record(db, member_id=member.id)
    await db.commit()

    # Token delivered via httpOnly cookie — no URL params (avoids token-in-URL logging)
    redirect_url = f"{settings.frontend_url}/oauth/callback"

    response = RedirectResponse(url=redirect_url, status_code=302)
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token_value)
    response.delete_cookie(key="oauth_code_verifier", path=COOKIE_PATH)
    response.delete_cookie(key="oauth_state", path=COOKIE_PATH)
    return response


# ── Token management ─────────────────────────────────────────────────────────


@router.post("/refresh")
async def refresh_access_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Refresh an expired access token using the refresh token cookie.

    Implements token rotation with replay detection.
    """
    token_value = request.cookies.get(COOKIE_KEY, "")
    if not token_value:
        raise AuthenticationError(
            "AUTH_MISSING_REFRESH_TOKEN", "No refresh token cookie"
        )

    user_id, member_id, team_id, role, worker_id, new_token_value = (
        await verify_and_rotate_refresh_token(db, token_value)
    )
    await db.commit()

    # P10-B17: look up is_super_admin from User table for JWT + response
    is_super_admin = False
    force_pw_change = False
    effective_user_id = user_id
    if user_id:
        user_result = await db.execute(
            select(User.is_super_admin, User.force_password_change).where(
                User.id == user_id
            )
        )
        user_row = user_result.one_or_none()
        if user_row:
            is_super_admin = user_row.is_super_admin
            force_pw_change = user_row.force_password_change
    elif member_id:
        # OAuth path: look up Member → User for is_super_admin
        oauth_user_id = await db.scalar(
            select(Member.user_id).where(Member.id == member_id)
        )
        if oauth_user_id:
            effective_user_id = oauth_user_id
            user_result = await db.execute(
                select(User.is_super_admin, User.force_password_change).where(
                    User.id == oauth_user_id
                )
            )
            user_row = user_result.one_or_none()
            if user_row:
                is_super_admin = user_row.is_super_admin
                force_pw_change = user_row.force_password_change

    access_token = create_access_token(
        user_id=user_id,
        actor_id=worker_id,
        team_id=team_id,
        role=role,
        is_super_admin=is_super_admin,
    )

    # Fetch display name
    display_name_result = await db.execute(
        select(Member.display_name).where(Member.id == member_id)
    )
    display_name = display_name_result.scalar_one_or_none() or ""

    content = TokenResponse(
        access_token=access_token,
        actor_id=worker_id,
        member_id=member_id,
        team_id=team_id,
        role=role,
        display_name=display_name,
        expires_in=settings.jwt_expire_minutes * 60,
        is_super_admin=is_super_admin,
        force_password_change=force_pw_change,
        user_id=effective_user_id,
    ).model_dump()

    response = JSONResponse(content=content)
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, new_token_value)
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Log out — revoke the refresh token and clear the cookie."""
    token_value = request.cookies.get(COOKIE_KEY, "")
    if token_value:
        await revoke_refresh_token(db, token_value)
        await db.commit()

    response = Response(status_code=204)
    _clear_access_cookie(response)
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=AuthStatusResponse)
async def auth_me(
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> AuthStatusResponse:
    """Return the current authenticated actor's status.

    P10-B17: includes is_super_admin and force_password_change for
    frontend permission gating and password-change enforcement.
    """
    # For human actors, look up force_password_change from User table
    # (not in JWT — must be fresh on each /me call for correctness)
    force_pw_change = False
    if actor.user_id:
        user_result = await db.execute(
            select(User.force_password_change, User.is_super_admin).where(
                User.id == actor.user_id
            )
        )
        user_row = user_result.one_or_none()
        if user_row:
            force_pw_change = user_row.force_password_change
            # Use DB as source of truth for is_super_admin
            is_super_admin = user_row.is_super_admin
        else:
            is_super_admin = actor.is_super_admin
    else:
        is_super_admin = actor.is_super_admin

    return AuthStatusResponse(
        authenticated=True,
        actor_id=actor.actor_id,
        member_id=actor.actor_id,  # P10-B7: actor_id is worker_id; kept for backward compat
        team_id=actor.team_id,
        role=actor.role,
        display_name=actor.name,
        is_super_admin=is_super_admin,
        force_password_change=force_pw_change,
        user_id=actor.user_id,
    )
