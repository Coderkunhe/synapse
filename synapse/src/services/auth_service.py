"""认证服务 — OAuth (GitHub)、Email/Password、Refresh Token 轮换。

服务层模块。不持有事务 — 调用方（router）负责提交。
遵循与其他 Synapse 服务（worker_service 等）相同的模式。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    create_access_token,
    create_user_id,
    generate_refresh_token_value,
    hash_token,
)
from src.config import settings
from src.constants import ActorType, AuthErrorCode, WorkerActorType, WorkerStatus
from src.exceptions import AuthenticationError, ConflictError
from src.models.member import Member
from src.models.password_reset_token import PasswordResetToken
from src.models.refresh_token import RefreshToken
from src.models.team import Team
from src.models.user import User
from src.models.user_auth_method import UserAuthMethod
from src.models.worker import Worker
from src.services.event_store import event_store
from src.utils.id_gen import derive_id, generate_id
from src.utils.security import hash_password, is_valid_email, verify_password


# ── PKCE 工具函数 ───────────────────────────────────────────────────────────


def _base64url(data: bytes) -> str:
    """Base64url 编码，无填充 (RFC 7636)。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_pkce_pair() -> tuple[str, str]:
    """生成 PKCE code_verifier 和 code_challenge (S256)。

    返回：
        (code_verifier, code_challenge)
    """
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = _base64url(digest)
    return code_verifier, code_challenge


# ── GitHub OAuth ─────────────────────────────────────────────────────────────


def get_github_authorize_url(code_challenge: str, state: str) -> str:
    """构建带 PKCE 的 GitHub OAuth 授权 URL。"""
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "read:user user:email",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"https://github.com/login/oauth/authorize?{urlencode(params)}"


async def exchange_github_code(code: str, code_verifier: str) -> str:
    """用授权码换取 GitHub 访问令牌。

    返回 GitHub 访问令牌字符串。

    如果 GitHub 拒绝交换则抛出 AuthenticationError。
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        data = resp.json()
        if "error" in data:
            raise AuthenticationError(
                "OAUTH_EXCHANGE_FAILED",
                data.get("error_description", "OAuth code exchange failed"),
            )
        return data["access_token"]


async def get_github_user(access_token: str) -> dict:
    """从 GitHub 获取已认证用户的个人资料。

    返回包含以下键的字典：provider、subject（GitHub 用户 ID 字符串）、
    email、display_name、avatar_url。
    """
    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        user_data = user_resp.json()

        email = user_data.get("email")
        if not email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails", headers=headers
            )
            emails = emails_resp.json()
            primary = next((e for e in emails if e.get("primary")), None)
            if primary:
                email = primary["email"]

        return {
            "provider": "github",
            "subject": str(user_data["id"]),
            "email": email,
            "display_name": user_data.get("name") or user_data["login"],
            "avatar_url": user_data.get("avatar_url"),
        }


# ── Member 管理 ────────────────────────────────────────────────────────


async def upsert_member_via_oauth(
    db: AsyncSession,
    *,
    oauth_provider: str,
    oauth_subject: str,
    email: str | None,
    display_name: str,
    avatar_url: str | None,
) -> Member:
    """通过 OAuth 身份查找已有 Member，或创建新 Member。

    如果这是首次 OAuth 登录（不存在具有此身份的 Member），
    则自动创建新 Team + Member（admin）。

    返回 Member（已附加到 db session，尚未提交）。
    """
    user_id = create_user_id(oauth_provider, oauth_subject)

    # 通过 OAuth 身份查找已有 member
    result = await db.execute(
        select(Member).where(
            Member.oauth_provider == oauth_provider,
            Member.oauth_subject == oauth_subject,
        )
    )
    member = result.scalar_one_or_none()

    if member:
        # 更新可变资料字段
        member.display_name = display_name
        if avatar_url:
            member.avatar_url = avatar_url
        if email:
            member.email = email
        member.last_active_at = datetime.now(timezone.utc)
        return member

    # 首次登录 — 创建新 Team + Member（admin）
    team = Team(
        id=generate_id("team"),
        name=f"{display_name}'s Team",
    )
    db.add(team)

    member = Member(
        id=generate_id("member"),
        team_id=team.id,
        user_id=user_id,
        display_name=display_name,
        role="admin",  # 首个 member = admin
        email=email,
        oauth_provider=oauth_provider,
        oauth_subject=oauth_subject,
        avatar_url=avatar_url,
    )
    db.add(member)

    # 记录 member.joined 事件（与 invite_member 相同模式）
    await event_store.record(
        db,
        event_type="member.invited",
        team_id=team.id,
        actor_type=ActorType.HUMAN,
        actor_id=member.id,
        target_type="member",
        target_id=member.id,
        payload={
            "user_id": user_id,
            "oauth_provider": oauth_provider,
            "display_name": display_name,
        },
    )

    # P10-B7: Ensure human Worker exists for every OAuth Member.
    # derive_id is deterministic — idempotent across repeated logins.
    worker_id = derive_id(member.id, "worker")
    existing_worker = await db.get(Worker, worker_id)
    if not existing_worker:
        human_worker = Worker(
            id=worker_id,
            name=member.display_name or member.email or "Human",
            team_id=member.team_id,
            user_id=member.user_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
            api_key_hash=None,  # P10-B8: human workers use JWT, not API keys
        )
        db.add(human_worker)

    return member


# ── Email/Password 认证 ─────────────────────────────────────────────────


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
) -> tuple[User, str, str, str]:
    """注册新用户（email/password）。

    1. 校验 email 格式 + 唯一性
    2. 校验密码强度
    3. 创建 User + UserAuthMethod(provider="email")
    4. 自动创建 human Worker
    5. 发布 JWT + Refresh Token

    返回:
        (user, worker_id, access_token, refresh_token_value)

    Raises:
        ConflictError: email 已被注册
        AuthenticationError: email 格式无效 / 密码太弱
    """
    email = email.strip().lower()

    # 校验 email 格式
    if not is_valid_email(email):
        raise AuthenticationError(
            AuthErrorCode.INVALID_EMAIL,
            f"Invalid email address: {email}",
        )

    # 校验密码强度
    from src.utils.security import PASSWORD_MIN_LENGTH

    if len(password) < PASSWORD_MIN_LENGTH:
        raise AuthenticationError(
            AuthErrorCode.WEAK_PASSWORD,
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters",
        )

    # 检查 email 唯一性（通过 UserAuthMethod 的 provider+subject 唯一约束）
    existing = await db.execute(
        select(UserAuthMethod).where(
            UserAuthMethod.provider == "email",
            UserAuthMethod.subject == email,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError(
            AuthErrorCode.EMAIL_ALREADY_EXISTS,
            f"Email already registered: {email}",
        )

    # 创建 User
    user = User(
        id=generate_id("user"),
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # P100-B106: FK PRAGMA 启用后需先 flush User 再创建子实体

    # 创建 UserAuthMethod（provider="email", subject=email）
    auth_method = UserAuthMethod(
        id=generate_id("user_auth_method"),
        user_id=user.id,
        provider="email",
        subject=email,
    )
    db.add(auth_method)

    # 创建 human Worker（P10-B7 模式：人类 User 自动获得 Worker）
    worker_id = derive_id(user.id, "worker")
    worker = Worker(
        id=worker_id,
        name=display_name,
        user_id=user.id,
        actor_type=WorkerActorType.HUMAN,
        status=WorkerStatus.ACTIVE,
        api_key_hash=None,  # P10-B8: human workers use JWT
    )
    db.add(worker)

    # 发布 JWT access token
    access_token = create_access_token(
        user_id=user.id,
        actor_id=worker_id,
        team_id=None,  # 注册时尚未加入任何 Team
        role="",     # 注册时无角色
        actor_type=ActorType.HUMAN,
        is_super_admin=user.is_super_admin,  # P10-B17: DB 宽列首用
    )

    # 创建 Refresh Token（user_id 路径 — P10-B9）
    refresh_token_value = await create_refresh_token_record(
        db, user_id=user.id,
    )

    return user, worker_id, access_token, refresh_token_value


async def login_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
) -> tuple[User, str, str, str, tuple[str, str, str]]:
    """Email/Password 登录。

    1. 通过 UserAuthMethod(provider="email") 查找 User
    2. 验证密码
    3. 检查账号激活状态
    4. 确保 human Worker 存在
    5. 发布 JWT + Refresh Token

    返回:
        (user, worker_id, access_token, refresh_token_value)

    Raises:
        AuthenticationError: 凭证无效 / 账号已停用
    """
    email = email.strip().lower()

    # 通过 UserAuthMethod 查找
    result = await db.execute(
        select(UserAuthMethod).where(
            UserAuthMethod.provider == "email",
            UserAuthMethod.subject == email,
        )
    )
    auth_method = result.scalar_one_or_none()

    if auth_method is None:
        raise AuthenticationError(
            AuthErrorCode.INVALID_CREDENTIALS,
            "Invalid email or password",
        )

    # 获取 User
    user = await db.get(User, auth_method.user_id)
    if user is None:
        raise AuthenticationError(
            AuthErrorCode.INVALID_CREDENTIALS,
            "Invalid email or password",
        )

    # 验证密码
    if not user.password_hash or not verify_password(password, user.password_hash):
        raise AuthenticationError(
            AuthErrorCode.INVALID_CREDENTIALS,
            "Invalid email or password",
        )

    # 检查账号激活
    if not user.is_active:
        raise AuthenticationError(
            AuthErrorCode.INVALID_CREDENTIALS,
            "Account is disabled",
        )

    # 确保 human Worker 存在（P10-B7 模式）
    worker_id = derive_id(user.id, "worker")
    existing_worker = await db.get(Worker, worker_id)
    if not existing_worker:
        worker = Worker(
            id=worker_id,
            name=user.display_name,
            user_id=user.id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
            api_key_hash=None,
        )
        db.add(worker)

    # 查找 Member 记录以获取 team/role（email 用户可能已有 Member）
    # P11-B36: email 登录需解析团队身份，否则前端因 team_id="" 拒绝渲染
    member_result = await db.execute(
        select(Member).where(
            Member.team_id.isnot(None),
            Member.email == user.email,
        ).order_by(Member.created_at.asc()).limit(1)
    )
    member = member_result.scalar_one_or_none()

    # 发布 JWT access token
    access_token = create_access_token(
        user_id=user.id,
        actor_id=worker_id,
        team_id=member.team_id if member else "",
        role=member.role if member else "",
        actor_type=ActorType.HUMAN,
        is_super_admin=user.is_super_admin,  # P10-B17: DB 宽列首用
    )

    # 创建 Refresh Token
    refresh_token_value = await create_refresh_token_record(
        db, user_id=user.id,
    )

    return user, worker_id, access_token, refresh_token_value, (
        member.team_id if member else "",
        member.role if member else "",
        member.id if member else "",
    )


# ── Refresh Token 操作 ─────────────────────────────────────────────────


async def create_refresh_token_record(
    db: AsyncSession,
    *,
    member_id: str | None = None,
    user_id: str | None = None,
    family_id: str | None = None,
) -> str:
    """创建新的 RefreshToken 行。返回明文字符串令牌值。

    如果 family_id 为 None，则启动新 family（初始登录）。
    如果提供，则令牌延续已有 family（轮换）。

    P10-B9: 新增 user_id 参数 — email/password 认证路径使用 User
    而非 Member。两个参数至少提供一个。
    """
    if not member_id and not user_id:
        raise ValueError("member_id or user_id is required")

    token_value = generate_refresh_token_value()
    token_hash = hash_token(token_value)
    family_id = family_id or generate_id("refresh_token")
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )

    rt = RefreshToken(
        id=generate_id("refresh_token"),
        member_id=member_id,
        user_id=user_id,
        token_hash=token_hash,
        family_id=family_id,
        expires_at=expires_at,
    )
    db.add(rt)
    return token_value


async def verify_and_rotate_refresh_token(
    db: AsyncSession,
    token_value: str,
) -> tuple[str, str, str, str, str, str]:
    """验证 Refresh Token 并轮换。

    返回：
        (user_id, member_id, team_id, role, worker_id, new_refresh_token_value)

    以下情况抛出 AuthenticationError：
    - 令牌未找到 / 无效
    - 令牌已过期
    - 令牌已被使用（重放 → 整个 family 被撤销）
    """
    token_hash = hash_token(token_value)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()

    if rt is None:
        raise AuthenticationError(
            "AUTH_INVALID_REFRESH_TOKEN", "Invalid refresh token"
        )

    # 重放攻击：此令牌已被使用
    if rt.revoked_at is not None:
        await _revoke_family(db, rt.family_id)
        raise AuthenticationError(
            "AUTH_TOKEN_REUSE_DETECTED",
            "Refresh token reuse detected — all sessions revoked",
        )

    # 过期检查（expires_at 在 SQLite 中存储为 naive datetime —
    # 读取后需添加 UTC 时区才能与 aware datetime 比较）
    expires_at_aware = rt.expires_at.replace(tzinfo=timezone.utc)
    if expires_at_aware < datetime.now(timezone.utc):
        await _revoke_family(db, rt.family_id)
        raise AuthenticationError(
            "AUTH_REFRESH_TOKEN_EXPIRED", "Refresh token expired"
        )

    # 撤销当前令牌
    rt.revoked_at = datetime.now(timezone.utc)

    # P10-B10: 支持两条路径 — OAuth (member_id) 和 Email/Password (user_id)
    if rt.user_id:
        # Email/Password 认证路径
        user = await db.get(User, rt.user_id)
        if user is None:
            raise AuthenticationError("AUTH_USER_NOT_FOUND", "User not found")

        worker_id = derive_id(user.id, "worker")
        new_token_value = await create_refresh_token_record(
            db, user_id=user.id, family_id=rt.family_id
        )

        return (
            user.id,      # user_id
            "",           # member_id — not applicable for email/password
            "",           # team_id — determined at project join time
            "",           # role — determined at project join time
            worker_id,
            new_token_value,
        )

    # OAuth 认证路径（legacy）
    member_result = await db.execute(
        select(Member).where(Member.id == rt.member_id)
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise AuthenticationError("AUTH_MEMBER_NOT_FOUND", "Member not found")

    # 在同一 family 中创建轮换后的令牌
    new_token_value = await create_refresh_token_record(
        db, member_id=member.id, family_id=rt.family_id
    )

    return (
        member.user_id,
        member.id,
        member.team_id,
        member.role,
        derive_id(member.id, "worker"),
        new_token_value,
    )


async def revoke_refresh_token(db: AsyncSession, token_value: str) -> None:
    """撤销单个 Refresh Token（登出）。幂等。"""
    token_hash = hash_token(token_value)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
    )
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked_at = datetime.now(timezone.utc)


# ── Password Reset ────────────────────────────────────────────────────────

RESET_TOKEN_BYTES = 32  # 256-bit random token


async def initiate_password_reset(
    db: AsyncSession,
    *,
    email: str,
) -> str | None:
    """为给定邮箱创建密码重置令牌。

    无论邮箱是否存在都返回一致的消息（防用户枚举）。

    SMTP 已配置：通过邮件发送重置链接，返回 None。
    SMTP 未配置：返回明文令牌（开发/测试/气隙降级模式）。

    返回:
        明文令牌字符串（SMTP 未配置时），或 None（SMTP 已发送邮件，
        或邮箱不存在，或 SMTP 发送失败）。

    不抛出异常 — 调用方始终返回 200 统一消息。
    """
    email = email.strip().lower()

    # 查找 User — 通过 UserAuthMethod(provider="email")
    result = await db.execute(
        select(UserAuthMethod).where(
            UserAuthMethod.provider == "email",
            UserAuthMethod.subject == email,
        )
    )
    auth_method = result.scalar_one_or_none()
    if auth_method is None:
        return None  # 邮箱未注册 — 不泄露此信息

    user = await db.get(User, auth_method.user_id)
    if user is None:
        return None

    # 生成令牌
    token_value = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    token_hash = hash_token(token_value)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.reset_token_expire_minutes
    )

    reset_token = PasswordResetToken(
        id=generate_id("password_reset_token"),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_token)

    # P10-B15: SMTP 已配置 → 邮件发送；未配置 → 返回明文令牌（开发/测试/气隙降级）
    if settings.smtp_host:
        from src.services.email_service import send_password_reset_email

        await send_password_reset_email(
            to_email=email,
            reset_token=token_value,
        )
        return None

    return token_value  # 无 SMTP：令牌通过 API 响应返回


async def complete_password_reset(
    db: AsyncSession,
    *,
    token: str,
    new_password: str,
) -> None:
    """用重置令牌完成密码重置。

    1. 查找所有未使用的令牌记录
    2. 逐个比对 token hash
    3. 验证未过期、未使用
    4. 更新 User.password_hash
    5. 标记令牌为已使用

    Raises:
        AuthenticationError: INVALID_RESET_TOKEN / RESET_TOKEN_EXPIRED /
                             RESET_TOKEN_ALREADY_USED / WEAK_PASSWORD
    """
    from src.utils.security import PASSWORD_MIN_LENGTH, hash_password

    if len(new_password) < PASSWORD_MIN_LENGTH:
        raise AuthenticationError(
            AuthErrorCode.WEAK_PASSWORD,
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters",
        )

    token_hash = hash_token(token)

    # 查找匹配的未使用令牌（按 created_at 倒序 — 最新优先）
    result = await db.execute(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        .order_by(PasswordResetToken.created_at.desc())
    )
    reset_token = result.scalars().first()

    if reset_token is None:
        # 令牌可能已被使用或无效
        # 二次查询：检查是否已使用（区分错误消息）
        used_result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.isnot(None),
            )
        )
        if used_result.scalar_one_or_none():
            raise AuthenticationError(
                AuthErrorCode.RESET_TOKEN_ALREADY_USED,
                "Reset token has already been used",
            )
        raise AuthenticationError(
            AuthErrorCode.INVALID_RESET_TOKEN,
            "Invalid reset token",
        )

    # 检查过期
    expires_at_aware = reset_token.expires_at.replace(tzinfo=timezone.utc)
    if expires_at_aware < datetime.now(timezone.utc):
        raise AuthenticationError(
            AuthErrorCode.RESET_TOKEN_EXPIRED,
            "Reset token has expired",
        )

    # 更新密码
    user = await db.get(User, reset_token.user_id)
    if user is None:
        raise AuthenticationError(
            AuthErrorCode.INVALID_RESET_TOKEN,
            "Invalid reset token",
        )

    user.password_hash = hash_password(new_password)

    # 标记令牌已使用
    reset_token.used_at = datetime.now(timezone.utc)


async def _revoke_family(db: AsyncSession, family_id: str) -> None:
    """撤销同一 family 中所有活跃令牌（防盗措施）。"""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    for rt in result.scalars().all():
        rt.revoked_at = datetime.now(timezone.utc)
