"""P13-B8: State 维度多 Worker 测试。

测试覆盖:
  - Worker state snapshot 端点: GET /workers/me/state
  - State config 验证: file vs API primary_source
  - State 响应结构: identity · active tasks · auth requests

使用 B6 harness: _create_provisioned_worker + providers。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header
from tests.harness.fixtures import _create_provisioned_worker
from tests.harness.providers import (
    claude_code_provider_config,
    codex_cli_provider_config,
    custom_provider_config,
)


# ── State Config 验证 ───────────────────────────────────────────


class TestStateConfigValidation:
    """state 维度 config 结构 + 差异验证。"""

    def test_claude_state_primary_source_is_file(self):
        cfg = claude_code_provider_config()["state"]
        assert cfg["primary_source"] == "file"
        assert cfg["file_path"] == ".claude/_task-current.md"
        assert cfg["refresh_on_startup"] is True
        assert cfg["cache_ttl_seconds"] == 60

    def test_codex_state_primary_source_is_api(self):
        cfg = codex_cli_provider_config()["state"]
        assert cfg["primary_source"] == "api"
        assert cfg["file_path"] is None
        assert cfg["refresh_on_startup"] is False
        assert cfg["cache_ttl_seconds"] == 0

    def test_state_sources_differ(self):
        """file vs api — 两种不同的状态数据源。"""
        claude_src = claude_code_provider_config()["state"]["primary_source"]
        codex_src = codex_cli_provider_config()["state"]["primary_source"]
        assert claude_src != codex_src

    def test_file_state_has_path(self):
        """file-based state 必须有 file_path。"""
        cfg = claude_code_provider_config()["state"]
        assert cfg["file_path"] is not None
        assert len(cfg["file_path"]) > 0

    def test_api_state_has_no_file_path(self):
        """api-only state 不需要 file_path。"""
        cfg = codex_cli_provider_config()["state"]
        assert cfg["file_path"] is None

    def test_cache_ttl_for_file_state(self):
        """file-based state 使用缓存 TTL。"""
        cfg = claude_code_provider_config()["state"]
        assert cfg["cache_ttl_seconds"] > 0

    def test_no_cache_for_api_state(self):
        """api-based state 不缓存（实时查询）。"""
        cfg = codex_cli_provider_config()["state"]
        assert cfg["cache_ttl_seconds"] == 0

    def test_custom_state_config(self):
        cfg = custom_provider_config(state={
            "primary_source": "memory",
            "cache_ttl_seconds": 30,
        })
        assert cfg["state"]["primary_source"] == "memory"
        assert cfg["state"]["cache_ttl_seconds"] == 30


# ── Worker State 端点 ───────────────────────────────────────────


class TestWorkerStateEndpoint:
    """GET /workers/me/state — Worker state snapshot (P12-B5)。"""

    @pytest.mark.asyncio
    async def test_get_worker_state_returns_snapshot(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Worker 获取自身 state snapshot → 200 · 含 identity。"""
        worker = await _create_provisioned_worker(
            client, seed, "State-Worker", claude_code_provider_config(),
        )

        resp = await client.get(
            f"/v1/workers/me/state?project_id={worker['project_id']}",
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 200, (
            f"State endpoint failed: {resp.status_code} {resp.text}"
        )
        state = resp.json()

        # 验证关键字段
        assert "worker_id" in state, f"State should include worker_id: {state}"
        assert state["worker_id"] == worker["worker_id"]
        assert state["worker_name"] is not None

    @pytest.mark.asyncio
    async def test_get_worker_state_includes_role(
        self, client: AsyncClient, seed: SeedData,
    ):
        """State snapshot 应包含 resolved role。"""
        worker = await _create_provisioned_worker(
            client, seed, "Role-State", claude_code_provider_config(),
        )

        resp = await client.get(
            f"/v1/workers/me/state?project_id={worker['project_id']}",
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 200
        state = resp.json()

        assert "role" in state, f"State should include role: {state}"

    @pytest.mark.asyncio
    async def test_get_worker_state_without_auth_rejected(
        self, client: AsyncClient, seed: SeedData,
    ):
        """无认证访问 state 端点 → 401。"""
        worker = await _create_provisioned_worker(
            client, seed, "NoAuth-State", claude_code_provider_config(),
        )

        resp = await client.get(
            f"/v1/workers/me/state?project_id={worker['project_id']}",
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_worker_state_same_team_different_project_allowed(
        self, client: AsyncClient, seed: SeedData,
    ):
        """同 team 不同 project — state 端点检查 team 归属，应允许访问。"""
        worker = await _create_provisioned_worker(
            client, seed, "SameTeam-State", claude_code_provider_config(),
        )
        other = await _create_provisioned_worker(
            client, seed, "OtherProj-State", claude_code_provider_config(),
        )

        resp = await client.get(
            f"/v1/workers/me/state?project_id={other['project_id']}",
            headers=auth_header(worker["api_key"]),
        )
        # 同 team → 允许（state 端点仅检查 team 归属，不检查 project 角色）
        assert resp.status_code == 200, (
            f"Same-team different project should be allowed, got {resp.status_code}"
        )
        state = resp.json()
        assert state["worker_id"] == worker["worker_id"]
        assert state["project_id"] == other["project_id"]

    @pytest.mark.asyncio
    async def test_codex_worker_state_endpoint(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Codex Worker（api state source）也应能获取 state snapshot。"""
        worker = await _create_provisioned_worker(
            client, seed, "Codex-State", codex_cli_provider_config(),
        )

        resp = await client.get(
            f"/v1/workers/me/state?project_id={worker['project_id']}",
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 200
        state = resp.json()
        assert state["worker_id"] == worker["worker_id"]

    @pytest.mark.asyncio
    async def test_worker_state_missing_project_id_rejected(
        self, client: AsyncClient, seed: SeedData,
    ):
        """缺少 project_id query param → 422。"""
        worker = await _create_provisioned_worker(
            client, seed, "NoProj-State", claude_code_provider_config(),
        )

        resp = await client.get(
            "/v1/workers/me/state",
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 422, (
            f"Missing project_id should return 422, got {resp.status_code}"
        )
