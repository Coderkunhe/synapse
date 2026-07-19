"""OAuth 认证端点 E2E 测试。

覆盖:
- GET  /v1/auth/oauth/github          — 发起流程，PKCE cookie
- GET  /v1/auth/oauth/github/callback — state 校验，缺失参数
- GET  /v1/auth/me                    — 已认证 / 未认证
- POST /v1/auth/refresh               — 基于 cookie 的刷新
- POST /v1/auth/logout                — 登出 + cookie 清除
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def _get_set_cookie_headers(res) -> list[str]:
    """从 httpx 响应中提取所有 Set-Cookie 头（httpx 使用 multi_items）。"""
    return [v for k, v in res.headers.multi_items() if k.lower() == "set-cookie"]


# ── GET /v1/auth/oauth/github ────────────────────────────────────────────────


class TestOAuthGitHubAuthorize:
    """发起 GitHub OAuth 流程。"""

    async def test_redirects_to_github(self, client: AsyncClient):
        """GET /v1/auth/oauth/github → 302 重定向到 GitHub authorize URL。"""
        res = await client.get("/v1/auth/oauth/github", follow_redirects=False)

        assert res.status_code == 302
        location = res.headers["location"]
        assert "github.com/login/oauth/authorize" in location
        assert "code_challenge_method=S256" in location
        assert "code_challenge=" in location

    async def test_sets_pkce_cookies(self, client: AsyncClient):
        """应设置 oauth_code_verifier 和 oauth_state cookie。"""
        res = await client.get("/v1/auth/oauth/github", follow_redirects=False)

        cookies = _get_set_cookie_headers(res)
        cookie_names = [c.split(";")[0].split("=")[0] for c in cookies]
        assert "oauth_code_verifier" in cookie_names
        assert "oauth_state" in cookie_names

    async def test_pkce_cookies_are_httponly(self, client: AsyncClient):
        """PKCE cookie 应为 httpOnly 以确保安全。"""
        res = await client.get("/v1/auth/oauth/github", follow_redirects=False)

        for cookie in _get_set_cookie_headers(res):
            assert "httponly" in cookie.lower()


# ── GET /v1/auth/oauth/github/callback ───────────────────────────────────────


class TestOAuthCallbackValidation:
    """验证回调参数 — state、verifier、code。"""

    async def test_missing_state(self, client: AsyncClient):
        """缺少 state → 302 到 login?error=invalid_state。"""
        res = await client.get(
            "/v1/auth/oauth/github/callback",
            params={"code": "test-code"},
            follow_redirects=False,
        )

        assert res.status_code == 302
        assert "error=invalid_state" in res.headers["location"]

    async def test_missing_code_verifier(self, client: AsyncClient):
        """缺少 PKCE verifier cookie → 302 到 login?error=missing_verifier。"""
        # 设置 state cookie 但不设置 verifier cookie
        cookies = {"oauth_state": "test-state"}
        res = await client.get(
            "/v1/auth/oauth/github/callback",
            params={"code": "test-code", "state": "test-state"},
            cookies=cookies,
            follow_redirects=False,
        )

        assert res.status_code == 302
        assert "error=missing_verifier" in res.headers["location"]

    async def test_state_mismatch(self, client: AsyncClient):
        """查询参数中的 state 与 cookie 不匹配 → 302 到 login?error=invalid_state。"""
        cookies = {"oauth_state": "real-state", "oauth_code_verifier": "test-verifier"}
        res = await client.get(
            "/v1/auth/oauth/github/callback",
            params={"code": "test-code", "state": "wrong-state"},
            cookies=cookies,
            follow_redirects=False,
        )

        assert res.status_code == 302
        assert "error=invalid_state" in res.headers["location"]


# ── GET /v1/auth/me ──────────────────────────────────────────────────────────


class TestAuthMe:
    """当前认证状态端点。"""

    async def test_authenticated(self, client: AsyncClient, seed):
        """有效 JWT → 200 返回 AuthStatusResponse。"""
        res = await client.get("/v1/auth/me", headers=auth_header(seed.token))

        assert res.status_code == 200
        data = res.json()
        assert data["authenticated"] is True
        assert data["member_id"] == seed.worker_id
        assert data["team_id"] == seed.team_id
        assert data["role"] == "admin"
        # display_name 来自 ActorInfo.name，JWT 认证时为 None
        # （get_current_actor 不会从 JWT payload 中提取名称）

    async def test_unauthenticated_no_token(self, client: AsyncClient):
        """无 token → 401。"""
        res = await client.get("/v1/auth/me")

        assert res.status_code == 401

    async def test_unauthenticated_invalid_token(self, client: AsyncClient):
        """无效 JWT → 401。"""
        res = await client.get(
            "/v1/auth/me", headers=auth_header("not.a.valid.token")
        )

        assert res.status_code == 401


# ── POST /v1/auth/refresh ────────────────────────────────────────────────────


class TestRefreshToken:
    """通过 httpOnly cookie 刷新 access token。"""

    async def test_no_refresh_cookie(self, client: AsyncClient):
        """无 refresh_token cookie → 401 AUTH_MISSING_REFRESH_TOKEN。"""
        res = await client.post("/v1/auth/refresh")

        assert res.status_code == 401
        data = res.json()
        # 错误响应格式：{"error": {"code": ..., "message": ..., "details": {}}}
        assert "AUTH_MISSING_REFRESH_TOKEN" in data["error"]["code"]

    async def test_invalid_refresh_cookie(self, client: AsyncClient):
        """无效 token 值 → 401。"""
        cookies = {"refresh_token": "not-a-real-token-value"}
        res = await client.post("/v1/auth/refresh", cookies=cookies)

        assert res.status_code == 401
        data = res.json()
        assert "AUTH_INVALID_REFRESH_TOKEN" in data["error"]["code"]


# ── POST /v1/auth/logout ─────────────────────────────────────────────────────


class TestLogout:
    """登出端点。"""

    async def test_logout_no_cookie_is_idempotent(self, client: AsyncClient):
        """无 cookie → 204（幂等 — 无任何需要撤销的内容）。"""
        res = await client.post("/v1/auth/logout")

        assert res.status_code == 204

    async def test_logout_clears_cookie(self, client: AsyncClient):
        """登出应清除 refresh_token cookie，即使没有有效 token。"""
        res = await client.post("/v1/auth/logout")

        assert res.status_code == 204
        # 应包含清除 refresh_token 的 Set-Cookie
        cookies = _get_set_cookie_headers(res)
        refresh_cookies = [c for c in cookies if "refresh_token" in c]
        assert len(refresh_cookies) >= 1
        cookie = refresh_cookies[0]
        assert 'refresh_token=""' in cookie or "Max-Age=0" in cookie or "expires=" in cookie.lower()
