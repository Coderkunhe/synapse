"""P11-B100: CapabilityAudit — POST + GET 端点测试。

覆盖：
- POST /projects/{pid}/capability-audits（Worker 创建审计记录）
- GET /projects/{pid}/capability-audits（admin 查询审计列表）
- 权限验证（无认证 → 401，非 admin → 403）
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ensure_project_role


def _uniq_slug(prefix: str) -> str:
    import secrets
    return f"{prefix}-{secrets.token_hex(4)}"


# ═══════════════════════════════════════════════════════════════════
# POST /projects/{project_id}/capability-audits
# ═══════════════════════════════════════════════════════════════════


class TestCreateCapabilityAudit:
    """Worker 直接创建审计记录 — 安全命令（免审批）路径。"""

    @pytest.mark.asyncio
    async def test_create_audit_safe_command_success(
        self, client: AsyncClient, seed: SeedData
    ):
        """Worker 创建安全命令审计记录 → 201 + 响应字段完整。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-safe")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 Safe", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        # 创建 Worker
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Audit Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        # Handshake
        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "preferred_channel": "websocket",
            },
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        # 创建审计记录（安全命令 — 无 authorization_request_id）
        audit_resp = await client.post(
            f"/v1/projects/{project_id}/capability-audits",
            json={
                "capability_id": "shell_dangerous",
                "command": "echo safe",
                "exit_code": 0,
                "duration_ms": 42,
                "outcome": "success",
                "authorization_request_id": None,
            },
            headers=worker_headers,
        )
        assert audit_resp.status_code == 201, audit_resp.text
        data = audit_resp.json()

        assert data["id"].startswith("ca_")
        assert data["project_id"] == project_id
        assert data["worker_id"] == worker_id
        assert data["capability_id"] == "shell_dangerous"
        assert data["command"] == "echo safe"
        assert data["exit_code"] == 0
        assert data["duration_ms"] == 42
        assert data["outcome"] == "success"
        assert data["authorization_request_id"] is None
        assert data["actor_type"] == "worker"
        assert data["actor_id"] == worker_id
        assert data["worker_name"] == "Audit Worker"
        assert data["created_at"] is not None

    @pytest.mark.asyncio
    async def test_create_audit_failure_outcome(
        self, client: AsyncClient, seed: SeedData
    ):
        """Worker 上报失败的安全命令 → outcome=failure 正确持久化。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-fail")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 Fail", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Fail Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_headers = auth_header(agent_resp.json()["api_key"])
        worker_id = agent_resp.json()["worker"]["id"]

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "preferred_channel": "websocket",
            },
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        audit_resp = await client.post(
            f"/v1/projects/{project_id}/capability-audits",
            json={
                "capability_id": "shell_dangerous",
                "command": "rm -rf /tmp/test",
                "exit_code": 1,
                "duration_ms": 100,
                "outcome": "failure",
                "authorization_request_id": None,
            },
            headers=worker_headers,
        )
        assert audit_resp.status_code == 201, audit_resp.text
        data = audit_resp.json()

        assert data["outcome"] == "failure"
        assert data["exit_code"] == 1
        assert data["command"] == "rm -rf /tmp/test"

    @pytest.mark.asyncio
    async def test_create_audit_requires_auth(
        self, client: AsyncClient, seed: SeedData
    ):
        """无认证请求 → 401。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-noauth")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 NoAuth", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        resp = await client.post(
            f"/v1/projects/{project_id}/capability-audits",
            json={
                "capability_id": "shell_dangerous",
                "command": "echo test",
                "exit_code": 0,
                "duration_ms": 10,
                "outcome": "success",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_audit_rejects_nonexistent_project(
        self, client: AsyncClient, seed: SeedData
    ):
        """Worker 上报一条记录到一个不存在的项目 → 404。"""
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Ghost Worker", "provider": "claude"},
            headers=auth_header(seed.token),
        )
        assert agent_resp.status_code == 201
        worker_headers = auth_header(agent_resp.json()["api_key"])

        resp = await client.post(
            "/v1/projects/prj_nonexistent000000000000000000/capability-audits",
            json={
                "capability_id": "shell_dangerous",
                "command": "echo ghost",
                "exit_code": 0,
                "duration_ms": 5,
                "outcome": "success",
            },
            headers=worker_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_audit_invalid_outcome(
        self, client: AsyncClient, seed: SeedData
    ):
        """outcome 不是 success/failure → 422 校验错误。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-invout")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 InvOut", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "InvOut Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_headers = auth_header(agent_resp.json()["api_key"])

        resp = await client.post(
            f"/v1/projects/{project_id}/capability-audits",
            json={
                "capability_id": "shell_dangerous",
                "command": "echo bad",
                "exit_code": 0,
                "duration_ms": 10,
                "outcome": "unknown",
            },
            headers=worker_headers,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# GET /projects/{project_id}/capability-audits
# ═══════════════════════════════════════════════════════════════════


class TestListCapabilityAudits:
    """Admin 查询 capability 审计记录列表。"""

    @pytest.mark.asyncio
    async def test_list_audits_empty(
        self, client: AsyncClient, seed: SeedData
    ):
        """无审计记录 → 返回空列表。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-empty")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 Empty", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        resp = await client.get(
            f"/v1/projects/{project_id}/capability-audits",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_list_audits_with_data(
        self, client: AsyncClient, seed: SeedData
    ):
        """创建 2 条审计记录 → 列表返回 2 条，按时间降序。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-list")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 List", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        # 创建 Worker
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "List Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "preferred_channel": "websocket",
            },
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        # 创建 2 条记录
        for i in range(2):
            resp = await client.post(
                f"/v1/projects/{project_id}/capability-audits",
                json={
                    "capability_id": f"test_cap_{i}",
                    "command": f"test command {i}",
                    "exit_code": 0,
                    "duration_ms": 10 + i,
                    "outcome": "success",
                },
                headers=worker_headers,
            )
            assert resp.status_code == 201

        # 查询列表
        list_resp = await client.get(
            f"/v1/projects/{project_id}/capability-audits",
            headers=headers,
        )
        assert list_resp.status_code == 200, list_resp.text
        data = list_resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        # 时间降序：第二条先返回
        assert data["items"][0]["command"] == "test command 1"
        assert data["items"][1]["command"] == "test command 0"
        # 富化字段
        for item in data["items"]:
            assert item["worker_name"] == "List Worker"

    @pytest.mark.asyncio
    async def test_list_audits_filter_by_outcome(
        self, client: AsyncClient, seed: SeedData
    ):
        """按 outcome=success 过滤 → 只返回 success 记录。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-filt")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 Filter", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Filter Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_headers = auth_header(agent_resp.json()["api_key"])
        worker_id = agent_resp.json()["worker"]["id"]

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "preferred_channel": "websocket",
            },
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        # 创建 1 success + 1 failure
        for outcome in ("success", "failure"):
            resp = await client.post(
                f"/v1/projects/{project_id}/capability-audits",
                json={
                    "capability_id": "test",
                    "command": f"cmd_{outcome}",
                    "exit_code": 0 if outcome == "success" else 1,
                    "duration_ms": 10,
                    "outcome": outcome,
                },
                headers=worker_headers,
            )
            assert resp.status_code == 201

        # 只查 success
        list_resp = await client.get(
            f"/v1/projects/{project_id}/capability-audits?outcome=success",
            headers=headers,
        )
        assert list_resp.status_code == 200, list_resp.text
        data = list_resp.json()
        assert data["total"] == 1
        assert data["items"][0]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_list_audits_requires_permission(
        self, client: AsyncClient, seed: SeedData
    ):
        """非 admin Worker 查询 → 202 AUTHORIZATION_PENDING（api_auth 授权管道触发）。

        Worker 缺少 capability_audit:read 权限时，系统不直接返回 403，
        而是创建 AuthorizationRequest 等待 Human 审批。这是 api_auth 授权管道的设计。
        """
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-perm")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 Perm", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        # 创建一个普通 Worker（只有 member 角色，无 admin）
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "NonAdmin Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_headers = auth_header(agent_resp.json()["api_key"])
        worker_id = agent_resp.json()["worker"]["id"]

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "preferred_channel": "websocket",
            },
            headers=worker_headers,
        )

        # 只分配 member 角色（不足够 capability_audit:read 需要的 admin）
        await ensure_project_role(client, project_id, worker_id, "member", headers)

        resp = await client.get(
            f"/v1/projects/{project_id}/capability-audits",
            headers=worker_headers,
        )
        # api_auth 管道：权限不足 → 202 + AUTHORIZATION_PENDING
        assert resp.status_code == 202, f"Unexpected {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["error"]["code"] == "AUTHORIZATION_PENDING"
        assert "authorization_request_id" in data["error"]["details"]

    @pytest.mark.asyncio
    async def test_list_audits_builder_can_read_with_admin_role(
        self, client: AsyncClient, seed: SeedData
    ):
        """具有 admin 角色的 Worker → 可以查询审计列表。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b100-adminw")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B100 AdminW", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Admin Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_headers = auth_header(agent_resp.json()["api_key"])
        worker_id = agent_resp.json()["worker"]["id"]

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "preferred_channel": "websocket",
            },
            headers=worker_headers,
        )

        # admin 角色 → capability_audit:read 放行
        await ensure_project_role(client, project_id, worker_id, "admin", headers)

        resp = await client.get(
            f"/v1/projects/{project_id}/capability-audits",
            headers=worker_headers,
        )
        assert resp.status_code == 200, resp.text
