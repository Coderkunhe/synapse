"""Email service 单元测试 + forgot-password E2E 测试。

P10-B15: Email 基础设施验证。
守卫条件：smtp_host 为空 → 返回 token（开发/测试/气隙）。
         smtp_host 已配置 → 发送邮件，不返回 token。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import async_session_factory
from src.services.email_service import (
    _load_template,
    send_email,
    send_password_reset_email,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """临时数据库 session — 用于验证写入记录。"""
    async with async_session_factory() as session:
        yield session


# ── email_service 单元测试 ──────────────────────────────────────────────────


class TestSendEmail:
    """send_email() — SMTP 发送核心。"""

    async def test_send_email_no_smtp_host(self, monkeypatch):
        """SMTP_HOST 为空 → 返回 False，不抛异常。"""
        monkeypatch.setattr(settings, "smtp_host", "")
        result = await send_email(
            to_email="test@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
            text_body="Hello",
        )
        assert result is False

    async def test_send_email_empty_text_body_default(self, monkeypatch):
        """text_body 默认空字符串 → 仍能正常降级。"""
        monkeypatch.setattr(settings, "smtp_host", "")
        result = await send_email(
            to_email="test@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
        )
        assert result is False  # SMTP 未配置，降级


class TestSendPasswordResetEmail:
    """send_password_reset_email() — 密码重置邮件。"""

    async def test_no_smtp_graceful_degradation(self, monkeypatch):
        """未配置 SMTP → send_password_reset_email 降级返回 False。"""
        monkeypatch.setattr(settings, "smtp_host", "")
        result = await send_password_reset_email(
            to_email="user@example.com",
            reset_token="some-token",
        )
        assert result is False

    async def test_template_rendering_included(self, monkeypatch):
        """模板加载成功（验证不抛异常）。"""
        monkeypatch.setattr(settings, "smtp_host", "")
        # 模板渲染在 send_password_reset_email 内部执行，
        # 因为 SMTP 未配置，在 send_email 阶段返回 False。
        # 如果模板有问题，会在渲染阶段抛出异常。
        result = await send_password_reset_email(
            to_email="user@example.com",
            reset_token="test-token-abc123",
        )
        assert result is False  # 降级但模板渲染成功（没抛异常）


class TestTemplateLoading:
    """模板加载和渲染。"""

    def test_load_html_template(self):
        """HTML 模板存在且包含占位符。"""
        template = _load_template("password_reset.html")
        rendered = template.substitute(
            reset_url="https://example.com/reset?token=abc",
            expires_in_minutes="60",
        )
        assert "https://example.com/reset?token=abc" in rendered
        assert "60 minutes" in rendered

    def test_load_text_template(self):
        """纯文本模板存在且包含占位符。"""
        template = _load_template("password_reset.txt")
        rendered = template.substitute(
            reset_url="https://example.com/reset?token=abc",
            expires_in_minutes="60",
        )
        assert "https://example.com/reset?token=abc" in rendered
        assert "60 minutes" in rendered

    def test_template_missing_placeholder_raises(self):
        """模板渲染缺少占位符 → KeyError。"""
        template = _load_template("password_reset.html")
        with pytest.raises(KeyError):
            template.substitute(reset_url="https://example.com")  # 缺少 expires_in_minutes


# ── forgot-password E2E 测试 ────────────────────────────────────────────────


class TestForgotPasswordNoSmtp:
    """smtp_host="" → token 在 API 响应中返回（开发/测试/气隙模式）。"""

    async def _register(self, client: AsyncClient, email: str, password: str, name: str):
        resp = await client.post("/v1/auth/register", json={
            "email": email,
            "password": password,
            "display_name": name,
        })
        assert resp.status_code == 201, resp.text

    async def test_no_smtp_returns_token(self, client: AsyncClient, monkeypatch):
        """smtp_host 为空 → forgot-password 响应包含 reset_token。"""
        monkeypatch.setattr(settings, "smtp_host", "")

        await self._register(client, "no-smtp@example.com", "securepass123", "NoSMTP")
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "no-smtp@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"]
        assert "reset_token" in data, (
            "SMTP 未配置时应返回 reset_token"
        )
        assert len(data["reset_token"]) > 0

    async def test_no_smtp_nonexistent_email_no_token(self, client: AsyncClient):
        """未注册邮箱 → 即使无 SMTP 也不泄露 token。"""
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "nobody-nosmtp@example.com",
        })
        assert resp.status_code == 200
        assert "reset_token" not in resp.json()


class TestForgotPasswordWithSmtp:
    """smtp_host 已配置 → token 通过邮件发送，不通过 API 响应泄露。"""

    async def _register(self, client: AsyncClient, email: str, password: str, name: str):
        resp = await client.post("/v1/auth/register", json={
            "email": email,
            "password": password,
            "display_name": name,
        })
        assert resp.status_code == 201, resp.text

    async def test_smtp_configured_no_token_in_response(
        self, client: AsyncClient, monkeypatch,
    ):
        """smtp_host 已配置 → forgot-password 响应不含 reset_token。"""
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

        await self._register(client, "smtp-on@example.com", "securepass123", "SMTP")
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "smtp-on@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"]
        assert "reset_token" not in data, (
            "SMTP 已配置时不应在 API 响应中泄露 reset_token"
        )

    async def test_smtp_configured_still_creates_db_record(
        self, client: AsyncClient, db_session, monkeypatch,
    ):
        """smtp_host 已配置 → 仍然创建 PasswordResetToken DB 记录。"""
        from sqlalchemy import select

        from src.models.password_reset_token import PasswordResetToken

        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

        await self._register(client, "smtp-db@example.com", "securepass123", "SMTP DB")
        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "smtp-db@example.com",
        })
        assert resp.status_code == 200

        # 验证 DB 记录（token 应该被创建，只是不在响应中）
        result = await db_session.execute(
            select(PasswordResetToken).order_by(
                PasswordResetToken.created_at.desc()
            ).limit(1)
        )
        prt = result.scalar_one_or_none()
        assert prt is not None, "PasswordResetToken 应该被创建"
        assert prt.token_hash is not None
        assert prt.used_at is None

    async def test_smtp_configured_nonexistent_email_same_response(
        self, client: AsyncClient, monkeypatch,
    ):
        """smtp_host 已配置 + 未注册邮箱 → 相同响应（防用户枚举）。"""
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

        resp = await client.post("/v1/auth/forgot-password", json={
            "email": "nobody-smtp@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"]
        assert "reset_token" not in data
