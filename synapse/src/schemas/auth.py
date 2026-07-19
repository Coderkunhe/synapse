"""认证 schema — OAuth 登录、Email/Password 注册和令牌管理。"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Email/Password 认证 ────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """Email/Password 注册请求。"""

    email: str = Field(
        ..., max_length=255,
        description="注册邮箱（全局唯一）",
    )
    password: str = Field(
        ..., min_length=8, max_length=128,
        description="明文密码（8-128 字符，服务端 bcrypt 哈希后存储）",
    )
    display_name: str = Field(
        ..., min_length=1, max_length=100,
        description="显示名称",
    )


class LoginRequest(BaseModel):
    """Email/Password 登录请求。"""

    email: str = Field(
        ..., max_length=255,
        description="登录邮箱",
    )
    password: str = Field(
        ..., max_length=128,
        description="明文密码",
    )


# ── Password Reset ──────────────────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    """忘记密码请求 — 发送重置链接到注册邮箱。"""

    email: str = Field(
        ..., max_length=255,
        description="注册邮箱（无论是否存在都返回成功，防用户枚举）",
    )


class ResetPasswordRequest(BaseModel):
    """重置密码请求 — 用重置令牌设置新密码。"""

    token: str = Field(
        ..., min_length=1,
        description="重置令牌明文（从 forgot-password 返回的 reset_token）",
    )
    new_password: str = Field(
        ..., min_length=8, max_length=128,
        description="新密码（8-128 字符）",
    )


# ── OAuth / Token ──────────────────────────────────────────────────────────


class TokenResponse(BaseModel):
    """OAuth 登录或令牌刷新成功后返回。"""

    access_token: str
    token_type: str = "bearer"
    actor_id: str  # P10-B7: worker_id (replaces member_id)
    member_id: str  # deprecated — use actor_id; kept for backward compat
    team_id: str
    role: str
    display_name: str
    expires_in: int  # 访问令牌过期时间（秒）
    is_super_admin: bool = False  # P10-B17: 超管标记
    force_password_change: bool = False  # P10-B17: 是否需强制改密
    user_id: str | None = None  # P10-B17: 稳定用户身份标识


class AuthStatusResponse(BaseModel):
    """前端 AuthContext 的当前认证状态。"""

    authenticated: bool
    actor_id: str | None = None  # P10-B7: worker_id (replaces member_id)
    member_id: str | None = None  # deprecated — use actor_id; kept for backward compat
    team_id: str | None = None
    role: str | None = None
    display_name: str | None = None
    is_super_admin: bool = False  # P10-B17: 超管标记
    force_password_change: bool = False  # P10-B17: 是否需强制改密
    user_id: str | None = None  # P10-B17: 稳定用户身份标识
