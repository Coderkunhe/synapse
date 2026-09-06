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

from tests.conftest import SeedData, auth_header, ensure_project_role
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

    @pytest.mark.asyncio
    async def test_worker_state_with_dependency_task_does_not_500(
        self, client: AsyncClient, seed: SeedData,
    ):
        """P16-B11 (PFL-251/266): 项目里存在带 depends_on 的任务时，state 端点不再 500。

        回归根因：``_task_summary`` 曾把 depends_on 的 JSON 字符串直接塞进
        ``list[str]``，非空依赖触发 Pydantic ResponseValidationError → 500。
        """
        worker = await _create_provisioned_worker(
            client, seed, "DepState-Worker", claude_code_provider_config(),
        )
        project_id = worker["project_id"]
        admin_headers = auth_header(seed.token)

        # 依赖任务（上游）
        dep_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "上游依赖任务",
                "description": "dependency upstream task",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "pytest full suite green"}],
            },
            headers=admin_headers,
        )
        assert dep_resp.status_code == 201, dep_resp.text
        dep_id = dep_resp.json()["id"]

        # 带非空 depends_on 的任务（下游）——默认 BACKLOG，会进 all_active_tasks
        child_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "带依赖的下游任务",
                "description": "task that depends on upstream",
                "priority": "p1",
                "depends_on": [{"task_id": dep_id, "type": "sequential"}],
                "verifications": [{"type": "manual", "description": "pytest full suite green"}],
            },
            headers=admin_headers,
        )
        assert child_resp.status_code == 201, child_resp.text
        child_id = child_resp.json()["id"]

        resp = await client.get(
            f"/v1/workers/me/state?project_id={project_id}",
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 200, (
            f"State endpoint 500'd on depends_on task: {resp.status_code} {resp.text}"
        )
        state = resp.json()

        # 下游任务应出现在 all_active_tasks，且 depends_on 是 task_id 字符串列表
        child = next(t for t in state["all_active_tasks"] if t["id"] == child_id)
        assert child["depends_on"] == [dep_id], (
            f"depends_on should be a list of task_ids, got {child['depends_on']!r}"
        )

    @pytest.mark.asyncio
    async def test_heartbeat_no_false_role_warning(
        self, client: AsyncClient, seed: SeedData,
    ):
        """P16-B11 (PFL-253): 角色经 project_actor_roles 解析时，心跳不再误报「默认分配 builder」。

        回归根因：heartbeat 曾用 metadata 级 ``resolve_role`` 独立告警，
        而真实角色来自 ``project_actor_roles``（get_project_role）。
        """
        worker = await _create_provisioned_worker(
            client, seed, "RoleWarn-State", claude_code_provider_config(),
        )

        resp = await client.post(
            f"/v1/workers/{worker['worker_id']}/heartbeat",
            json={"current_load": 0, "project_id": worker["project_id"]},
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["role"] == "builder", f"role should come from project_actor_roles: {body}"
        assert not any("默认分配 builder" in w for w in body["role_warnings"]), (
            f"role_warnings should not carry the metadata-fallback warning: {body['role_warnings']}"
        )

    @pytest.mark.asyncio
    async def test_worker_state_role_from_project_role(
        self, client: AsyncClient, seed: SeedData,
    ):
        """P16-B11 (PFL-253): state 快照的 role 应从 project_actor_roles 解析，而非 metadata fallback。"""
        worker = await _create_provisioned_worker(
            client, seed, "OrchRole-State", claude_code_provider_config(),
        )
        admin_headers = auth_header(seed.token)
        await ensure_project_role(
            client, worker["project_id"], worker["worker_id"], "orchestrator", admin_headers,
        )

        resp = await client.get(
            f"/v1/workers/me/state?project_id={worker['project_id']}",
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "orchestrator", (
            f"state role should be project-scoped, got {resp.json()['role']!r}"
        )
