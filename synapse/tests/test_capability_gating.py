"""P11-B95: Capability 硬约束 — Task 分配 + capability_exec 所有权校验。"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ensure_project_role, ready_task


def _uniq_slug(prefix: str) -> str:
    """生成唯一的项目 slug。"""
    import secrets
    return f"{prefix}-{secrets.token_hex(4)}"


# ═══════════════════════════════════════════════════════════════════
# P11-B95: Capability 硬约束（PFL-086 + PFL-094）
# ═══════════════════════════════════════════════════════════════════


class TestCapabilityGating:
    """Task 分配时必须校验 Worker 具备 required_capabilities（PFL-086）。"""

    @pytest.mark.asyncio
    async def test_assign_skips_when_no_required_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task 无 required_capabilities → 分配到任何 Worker 都应成功（向后兼容）。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b95-compat")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B95 Compat", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        # 注册没有 capabilities 的 Worker
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "NoCap Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": [], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        # 创建无 required_capabilities 的 Task
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "No Cap Required",
                "description": "Backward compat test",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "Verify backward compat test works correctly"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        # 分配 → 应成功（跳过 capability 检查）
        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": worker_id, "expected_version": version},
            headers=headers,
        )
        assert assign_resp.status_code == 200, assign_resp.text

    @pytest.mark.asyncio
    async def test_assign_rejects_worker_without_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task 有 required_capabilities 但 Worker 没有 → 409 WORKER_NO_CAPABILITIES。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b95-nocap")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B95 NoCap", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "NoCap Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        # Handshake 不声明任何能力
        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": [], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Needs Code Review",
                "description": "This task needs code_review capability",
                "priority": "p2",
                "required_capabilities": ["code_review"],
                "verifications": [{"type": "manual", "description": "Verify code review was done correctly"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": worker_id, "expected_version": version},
            headers=headers,
        )
        assert assign_resp.status_code == 409
        assert "WORKER_NO_CAPABILITIES" in assign_resp.text

    @pytest.mark.asyncio
    async def test_assign_rejects_worker_with_wrong_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task requires code_review，Worker 只有 coding → 409 WORKER_MISSING_CAPABILITIES。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b95-wrong")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B95 Wrong Cap", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "CodingOnly Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": ["coding"], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Needs Code Review",
                "description": "This task needs code_review capability",
                "priority": "p2",
                "required_capabilities": ["code_review"],
                "verifications": [{"type": "manual", "description": "Verify code review was done correctly"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": worker_id, "expected_version": version},
            headers=headers,
        )
        assert assign_resp.status_code == 409
        assert "WORKER_MISSING_CAPABILITIES" in assign_resp.text

    @pytest.mark.asyncio
    async def test_assign_allows_worker_with_matching_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task requires code_review，Worker 声明了 code_review → 200 成功。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b95-match")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B95 Match", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "CodeReview Worker", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": ["code_review"], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Needs Code Review",
                "description": "This task needs code_review capability",
                "priority": "p2",
                "required_capabilities": ["code_review"],
                "verifications": [{"type": "manual", "description": "Verify code review was done correctly"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": worker_id, "expected_version": version},
            headers=headers,
        )
        assert assign_resp.status_code == 200, assign_resp.text


# ═══════════════════════════════════════════════════════════════════
# P14-B10: Claim 路径 capability 硬约束（PFL-171）
# ═══════════════════════════════════════════════════════════════════


class TestClaimCapabilityGating:
    """Claim 路径（pull）与 assign 路径（push）同等的 capability 校验（P14-B10 PFL-171）。"""

    @pytest.mark.asyncio
    async def test_claim_skips_when_no_required_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task 无 required_capabilities → claim 成功（向后兼容）。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b10-claim-compat")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B10 Claim Compat", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "NoCap Claimer", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": [], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "No Cap Required - Claim",
                "description": "Claim backward compat test",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "Verify claim compat"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            json={"expected_version": version},
            headers=worker_headers,
        )
        assert claim_resp.status_code == 200, claim_resp.text

    @pytest.mark.asyncio
    async def test_claim_rejects_worker_without_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task 有 required_capabilities 但 Worker 声明空 → 409 WORKER_NO_CAPABILITIES。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b10-claim-nocap")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B10 Claim NoCap", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "EmptyCap Claimer", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": [], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Needs Code Review - Claim",
                "description": "Claim should be rejected",
                "priority": "p2",
                "required_capabilities": ["code_review"],
                "verifications": [{"type": "manual", "description": "Verify code review"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            json={"expected_version": version},
            headers=worker_headers,
        )
        assert claim_resp.status_code == 409
        assert "WORKER_NO_CAPABILITIES" in claim_resp.text

    @pytest.mark.asyncio
    async def test_claim_rejects_worker_with_wrong_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task requires code_review，Worker 只有 coding → 409 WORKER_MISSING_CAPABILITIES。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b10-claim-wrong")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B10 Claim WrongCap", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "CodingOnly Claimer", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": ["coding"], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Needs Code Review - Claim",
                "description": "Claim should be rejected - wrong capability",
                "priority": "p2",
                "required_capabilities": ["code_review"],
                "verifications": [{"type": "manual", "description": "Verify code review"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            json={"expected_version": version},
            headers=worker_headers,
        )
        assert claim_resp.status_code == 409
        assert "WORKER_MISSING_CAPABILITIES" in claim_resp.text

    @pytest.mark.asyncio
    async def test_claim_allows_worker_with_matching_capabilities(
        self, client: AsyncClient, seed: SeedData
    ):
        """Task requires code_review，Worker 声明了 code_review → 200 claim 成功。"""
        headers = auth_header(seed.token)
        slug = _uniq_slug("b10-claim-match")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B10 Claim Match", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "CodeReview Claimer", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201
        worker_id = agent_resp.json()["worker"]["id"]
        worker_headers = auth_header(agent_resp.json()["api_key"])

        await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": ["code_review"], "preferred_channel": "websocket"},
            headers=worker_headers,
        )

        await ensure_project_role(client, project_id, worker_id, "builder", headers)

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Needs Code Review - Claim",
                "description": "Claim should succeed with matching capability",
                "priority": "p2",
                "required_capabilities": ["code_review"],
                "verifications": [{"type": "manual", "description": "Verify code review"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201
        task_id = task_resp.json()["id"]

        await ready_task(client, task_resp.json(), seed.token)
        ready_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        version = ready_resp.json()["version_no"]

        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            json={"expected_version": version},
            headers=worker_headers,
        )
        assert claim_resp.status_code == 200, claim_resp.text
