"""Email/Password 认证 E2E 测试 — POST /v1/auth/register + /v1/auth/login。

P10-B10: 议题 2 首个用户可见端点。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import async_session_factory
from src.models.password_reset_token import PasswordResetToken
from src.models.refresh_token import RefreshToken
from src.models.user import User
from src.models.user_auth_method import UserAuthMethod
from src.models.worker import Worker
from src.utils.id_gen import derive_id


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """临时数据库 session — 用于验证写入记录。"""
    async with async_session_factory() as session:
        yield session


# ── POST /v1/auth/register ──────────────────────────────────────────────────


class TestRegister:
    """POST /v1/auth/register — email/password 注册。"""

    async def test_register_success(self, client: AsyncClient):
        """正常注册 → 201 + TokenResponse + cookie。"""
        resp = await client.post("/v1/auth/register", json={
            "email": "alice@example.com",
            "password": "securepass123",
            "display_name": "Alice",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["access_token"]
        assert data["actor_id"].startswith("ag_")
        assert data["display_name"] == "Alice"
        assert data["expires_in"] > 0
        # P10-B17: new fields
        assert "is_super_admin" in data
        assert data["is_super_admin"] is False  # new users are not super admin
        assert "force_password_change" in data
        assert data["force_password_change"] is False  # default
        assert "user_id" in data
        assert data["user_id"] is not None
        # 验证 cookie
        assert "access_token" in resp.cookies
        assert "refresh_token" in resp.cookies

    async def test_register_duplicate_email(self, client: AsyncClient):
        """重复邮箱注册 → 409 Conflict。"""
        payload = {
            "email": "bob@example.com",
            "password": "securepass123",
            "display_name": "Bob",
        }
        resp1 = await client.post("/v1/auth/register", json=payload)
        assert resp1.status_code == 201

        resp2 = await client.post("/v1/auth/register", json=payload)
        assert resp2.status_code == 409
        err = resp2.json()["error"]
        assert err["code"] == "EMAIL_ALREADY_EXISTS"

    async def test_register_invalid_email(self, client: AsyncClient):
        """无效 email 格式 → 401。"""
        resp = await client.post("/v1/auth/register", json={
            "email": "not-an-email",
            "password": "securepass123",
            "display_name": "Bad Email",
        })
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_EMAIL"

    async def test_register_email_no_tld(self, client: AsyncClient):
        """无 TLD 的邮箱（如 user@domain）→ 401 INVALID_EMAIL。"""
        resp = await client.post("/v1/auth/register", json={
            "email": "admin@localhost",
            "password": "securepass123",
            "display_name": "No TLD",
        })
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_EMAIL"

    async def test_register_weak_password(self, client: AsyncClient):
        """密码太短 → 422 (Pydantic min_length 校验在 service 层之前)。"""
        resp = await client.post("/v1/auth/register", json={
            "email": "short@example.com",
            "password": "1234567",  # 7 chars < min_length=8
            "display_name": "Short PW",
        })
        assert resp.status_code == 422

    async def test_register_creates_db_records(self, client: AsyncClient, db_session):
        """注册后在数据库创建 User + UserAuthMethod + Worker 记录。"""
        resp = await client.post("/v1/auth/register", json={
            "email": "charlie@example.com",
            "password": "securepass123",
            "display_name": "Charlie",
        })
        assert resp.status_code == 201

        # UserAuthMethod
        uam_result = await db_session.execute(
            select(UserAuthMethod).where(
                UserAuthMethod.provider == "email",
                UserAuthMethod.subject == "charlie@example.com",
            )
        )
        uam = uam_result.scalar_one_or_none()
        assert uam is not None

        # User
        user = await db_session.get(User, uam.user_id)
        assert user is not None
        assert user.email == "charlie@example.com"
        assert user.password_hash is not None
        assert user.display_name == "Charlie"
        assert user.is_active is True

        # human Worker
        worker = await db_session.get(Worker, derive_id(user.id, "worker"))
        assert worker is not None
        assert worker.actor_type == "human"
        assert worker.user_id == user.id

    async def test_register_email_case_insensitive(self, client: AsyncClient):
        """邮箱大小写不敏感 — 注册时 normalized 为小写。"""
        resp1 = await client.post("/v1/auth/register", json={
            "email": "Casey@Example.COM",
            "password": "securepass123",
            "display_name": "Casey",
        })
        assert resp1.status_code == 201

        # 用小写重复注册应冲突
        resp2 = await client.post("/v1/auth/register", json={
            "email": "casey@example.com",
            "password": "different123",
            "display_name": "Casey Dupe",
        })
        assert resp2.status_code == 409


# ── POST /v1/auth/login ─────────────────────────────────────────────────────


class TestLogin:
    """POST /v1/auth/login — email/password 登录。"""

    async def _register(self, client: AsyncClient, email: str, password: str, name: str):
        resp = await client.post("/v1/auth/register", json={
            "email": email,
            "password": password,
            "display_name": name,
        })
        assert resp.status_code == 201, resp.text
        return email, password, name

    async def test_login_success(self, client: AsyncClient):
        """正常登录 → 200 + TokenResponse + cookie。"""
        await self._register(client, "dave@example.com", "securepass123", "Dave")
        resp = await client.post("/v1/auth/login", json={
            "email": "dave@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["access_token"]
        assert data["actor_id"].startswith("ag_")
        assert data["display_name"] == "Dave"
        # P10-B17: new fields
        assert "is_super_admin" in data
        assert data["is_super_admin"] is False
        assert "force_password_change" in data
        assert "user_id" in data
        assert data["user_id"] is not None
        assert "access_token" in resp.cookies
        assert "refresh_token" in resp.cookies

    async def test_login_wrong_password(self, client: AsyncClient):
        """错误密码 → 401。"""
        await self._register(client, "eve@example.com", "securepass123", "Eve")
        resp = await client.post("/v1/auth/login", json={
            "email": "eve@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_login_unknown_email(self, client: AsyncClient):
        """未注册邮箱 → 401。"""
        resp = await client.post("/v1/auth/login", json={
            "email": "nobody@example.com",
            "password": "anything123",
        })
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_login_email_case_insensitive(self, client: AsyncClient):
        """邮箱大小写不敏感。"""
        await self._register(client, "FRANK@example.com", "securepass123", "Frank")
        resp = await client.post("/v1/auth/login", json={
            "email": "frank@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["display_name"] == "Frank"

    async def test_login_creates_refresh_token_record(self, client: AsyncClient, db_session):
        """登录后 refresh token 写入数据库（user_id 路径）。"""
        await self._register(client, "gina@example.com", "securepass123", "Gina")
        resp = await client.post("/v1/auth/login", json={
            "email": "gina@example.com",
            "password": "securepass123",
        })
        assert resp.status_code == 200

        # 验证 refresh token 记录
        result = await db_session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id.isnot(None),
                RefreshToken.revoked_at.is_(None),
            ).order_by(RefreshToken.created_at.desc()).limit(1)
        )
        rt = result.scalar_one_or_none()
        assert rt is not None, "Refresh token should exist in DB"
        assert rt.user_id is not None


# ── Token refresh after email/password login ─────────────────────────────────


class TestEmailAuthTokenRefresh:
    """验证 email/password 登录后的 refresh token 轮换。"""

    async def test_refresh_with_email_token(self, client: AsyncClient):
        """Email 登录 → 用 cookie refresh → 获取新 token。"""
        # 1. 注册
        resp = await client.post("/v1/auth/register", json={
            "email": "refresh@example.com",
            "password": "securepass123",
            "display_name": "Refresh Test",
        })
        assert resp.status_code == 201

        # 2. 用返回的 refresh cookie 刷新
        refresh_cookie = resp.cookies.get("refresh_token")
        assert refresh_cookie, "refresh_token cookie should be set"

        refresh_resp = await client.post(
            "/v1/auth/refresh",
            cookies={"refresh_token": refresh_cookie},
        )
        assert refresh_resp.status_code == 200, refresh_resp.text
        data = refresh_resp.json()
        assert data["access_token"]
        assert data["actor_id"].startswith("ag_")


# ── POST /v1/auth/forgot-password ──────────────────────────────────────────


class TestForgotPassword:
    """POST /v1/auth/forgot-password — 请求密码重置。"""

    async def _register(self, client: AsyncClient, email: str, password: str, name: str):
        resp = await client.post("/v1/auth/register", json={
            "email": email,
            "password": password,
            "display_name": name,
        })
        assert resp.status_code == 201, resp.text

    async def test_forgot_password_existing_email(self, client: AsyncClient):
        """已注册邮箱 → 200 + message（SMTP 配置时 token 不返回）。"""
        await self._register(client, "resetme@example.com", "securepass123", "Reset Me")
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "resetme@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"]
        # SMTP configured → token sent via email, not in response
        # SMTP not configured → token returned in response (dev mode)
        # Both modes return 200 + message; don't assert token presence

    async def test_forgot_password_nonexistent_email(self, client: AsyncClient):
        """未注册邮箱 → 200 + 相同 message（防用户枚举）。"""
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "nobody@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        # 不应泄露邮箱未注册
        assert "reset_token" not in data

    async def test_forgot_password_creates_db_record(self, client: AsyncClient, db_session):
        """忘记密码请求在 DB 中创建 PasswordResetToken 记录。"""
        await self._register(client, "token-db@example.com", "securepass123", "Token DB")
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "token-db@example.com",
        })
        assert resp.status_code == 200

        # 验证 DB 记录
        result = await db_session.execute(
            select(PasswordResetToken).order_by(
                PasswordResetToken.created_at.desc()
            ).limit(1)
        )
        prt = result.scalar_one_or_none()
        assert prt is not None, "PasswordResetToken should exist in DB"
        assert prt.token_hash is not None
        assert prt.used_at is None
        assert prt.expires_at is not None

    async def test_forgot_password_case_insensitive(self, client: AsyncClient):
        """邮箱大小写不敏感。"""
        await self._register(client, "CASE-TEST@example.com", "securepass123", "Case Test")
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "case-test@example.com",
        })
        assert resp.status_code == 200
        assert "message" in resp.json()


# ── POST /v1/auth/reset-password ───────────────────────────────────────────


class TestResetPassword:
    """POST /v1/auth/reset-password — 用令牌重置密码。"""

    async def _get_reset_token(
        self, client: AsyncClient, email: str, monkeypatch=None,
    ) -> str:
        """请求重置并返回 reset_token。

        SMTP 已配置时 token 通过邮件发送（不在 API 响应中）——
        临时关闭 SMTP 让 API 返回原始 token，用完恢复。
        SMTP 未配置时 token 直接在 API 响应中返回。
        """
        resp = await client.post("/v1/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200
        data = resp.json()
        if "reset_token" in data:
            return data["reset_token"]

        # SMTP configured — temporarily disable to get raw token in response
        assert monkeypatch is not None, (
            "monkeypatch required to disable SMTP for token retrieval"
        )
        import src.config
        monkeypatch.setattr(src.config.settings, "smtp_host", "")
        resp2 = await client.post("/v1/auth/forgot-password", json={"email": email})
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert "reset_token" in data2, (
            f"reset_token missing even with SMTP disabled: {data2}"
        )
        return data2["reset_token"]

    async def _register(self, client: AsyncClient, email: str, password: str, name: str):
        resp = await client.post("/v1/auth/register", json={
            "email": email,
            "password": password,
            "display_name": name,
        })
        assert resp.status_code == 201, resp.text

    async def test_reset_password_success(self, client: AsyncClient, monkeypatch):
        """用有效令牌重置密码 → 200 + 新密码可登录。"""
        await self._register(client, "reset-success@example.com", "oldpass123", "Reset OK")
        reset_token = await self._get_reset_token(client, "reset-success@example.com", monkeypatch)

        resp = await client.post("/v1/auth/reset-password", json={
            "token": reset_token,
            "new_password": "newpass456",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["message"]

        # 旧密码登录失败
        resp_old = await client.post("/v1/auth/login", json={
            "email": "reset-success@example.com",
            "password": "oldpass123",
        })
        assert resp_old.status_code == 401

        # 新密码登录成功
        resp_new = await client.post("/v1/auth/login", json={
            "email": "reset-success@example.com",
            "password": "newpass456",
        })
        assert resp_new.status_code == 200

    async def test_reset_password_invalid_token(self, client: AsyncClient):
        """无效令牌 → 401。"""
        resp = await client.post("/v1/auth/reset-password", json={
            "token": "this-is-not-a-valid-token",
            "new_password": "newpass456",
        })
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_RESET_TOKEN"

    async def test_reset_password_weak_password(self, client: AsyncClient):
        """弱新密码 → 422 (Pydantic min_length=8 在 schema 层拦截)。"""
        resp = await client.post("/v1/auth/reset-password", json={
            "token": "some-token",
            "new_password": "1234567",  # 7 chars
        })
        assert resp.status_code == 422

    async def test_reset_password_token_not_reusable(self, client: AsyncClient, monkeypatch):
        """令牌只能使用一次 — 第二次使用相同令牌失败。"""
        await self._register(client, "reuse@example.com", "oldpass123", "Reuse Test")
        reset_token = await self._get_reset_token(client, "reuse@example.com", monkeypatch)

        # 第一次 — 成功
        resp1 = await client.post("/v1/auth/reset-password", json={
            "token": reset_token,
            "new_password": "firstpass1",
        })
        assert resp1.status_code == 200

        # 第二次 — 拒绝
        resp2 = await client.post("/v1/auth/reset-password", json={
            "token": reset_token,
            "new_password": "secondpass2",
        })
        assert resp2.status_code == 401
        assert resp2.json()["error"]["code"] == "RESET_TOKEN_ALREADY_USED"

    async def test_reset_password_expired_token(self, client: AsyncClient, monkeypatch):
        """过期令牌 → 401 RESET_TOKEN_EXPIRED。"""
        await self._register(client, "expired@example.com", "oldpass123", "Expired Test")
        # First token — normal (used to verify the user exists, not for the actual test)
        await self._get_reset_token(client, "expired@example.com", monkeypatch)

        # Create an immediately-expired token by setting TTL to -1
        from src import config

        original_ttl = config.settings.reset_token_expire_minutes
        config.settings.reset_token_expire_minutes = -1  # expire immediately

        # Temporarily disable SMTP so the expired token is returned in the response
        original_smtp = config.settings.smtp_host
        config.settings.smtp_host = ""

        resp_token = await client.post("/v1/auth/forgot-password", json={
            "email": "expired@example.com",
        })
        expired_token = resp_token.json().get("reset_token")

        # Restore config
        config.settings.smtp_host = original_smtp
        config.settings.reset_token_expire_minutes = original_ttl

        assert expired_token is not None, "Expected expired token in response"
        resp = await client.post("/v1/auth/reset-password", json={
            "token": expired_token,
            "new_password": "newpass456",
        })
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "RESET_TOKEN_EXPIRED"
