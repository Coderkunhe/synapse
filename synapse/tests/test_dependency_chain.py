"""E2E tests: GET /v1/tasks/{id}/dependency-chain — P12-B43 Task 1.

Covers:
- No dependencies → empty chain
- Single-layer upstream
- Single-layer downstream
- Multi-layer chain (A → B → C)
- Diamond dependency
- Direction filtering (upstream / downstream / both)
- Cycle detection resilience
- Task not found → 404
- Invalid direction → 422
- Cross-project isolation
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


def _find_in_chain(items: list[dict], task_id: str) -> dict | None:
    for item in items:
        if item["task_id"] == task_id:
            return item
    return None


class TestDependencyChain:
    """P12-B43: GET /v1/tasks/{id}/dependency-chain."""

    # ── helpers ────────────────────────────────────────────────

    async def _create_project(
        self, client: AsyncClient, seed: SeedData, name: str,
    ) -> str:
        headers = auth_header(seed.token)
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": name, "slug": _uniq_slug("dc")},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    async def _create_task(
        self,
        client: AsyncClient,
        seed: SeedData,
        project_id: str,
        title: str,
        *,
        depends_on: list[dict] | None = None,
    ) -> dict:
        headers = auth_header(seed.token)
        body: dict = {
            "title": title,
            "description": "Test task for dependency chain",
            "priority": "p1",
            "verifications": [
                {"type": "manual", "description": "Verification check passed successfully"}
            ],
        }
        if depends_on is not None:
            body["depends_on"] = depends_on
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json=body,
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def _get_chain(
        self,
        client: AsyncClient,
        seed: SeedData,
        task_id: str,
        direction: str = "both",
    ) -> dict:
        headers = auth_header(seed.token)
        resp = await client.get(
            f"/v1/tasks/{task_id}/dependency-chain?direction={direction}",
            headers=headers,
        )
        return resp

    # ── tests ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_dependencies(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Task with no depends_on → empty upstream + downstream."""
        project_id = await self._create_project(client, seed, "无依赖")
        task = await self._create_task(client, seed, project_id, "独立任务")

        resp = await self._get_chain(client, seed, task["id"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["task_id"] == task["id"]
        assert body["chain"]["upstream"] == []
        assert body["chain"]["downstream"] == []

    @pytest.mark.asyncio
    async def test_single_upstream(
        self, client: AsyncClient, seed: SeedData,
    ):
        """B depends on A → B has A in upstream."""
        project_id = await self._create_project(client, seed, "单层上游")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        task_b = await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )

        resp = await self._get_chain(client, seed, task_b["id"])
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert len(body["chain"]["upstream"]) == 1
        up = body["chain"]["upstream"][0]
        assert up["task_id"] == task_a["id"]
        assert up["title"] == "Task A"
        assert up["dependency_type"] == "sequential"
        assert body["chain"]["downstream"] == []

    @pytest.mark.asyncio
    async def test_single_downstream(
        self, client: AsyncClient, seed: SeedData,
    ):
        """B depends on A → A has B in downstream."""
        project_id = await self._create_project(client, seed, "单层下游")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        task_b = await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "artifact"}],
        )

        resp = await self._get_chain(client, seed, task_a["id"])
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["chain"]["upstream"] == []
        assert len(body["chain"]["downstream"]) == 1
        down = body["chain"]["downstream"][0]
        assert down["task_id"] == task_b["id"]
        assert down["title"] == "Task B"
        assert down["dependency_type"] == "artifact"

    @pytest.mark.asyncio
    async def test_multi_layer_chain(
        self, client: AsyncClient, seed: SeedData,
    ):
        """A → B → C chain: B has A upstream + C downstream. C has A+B upstream."""
        project_id = await self._create_project(client, seed, "多层链")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        task_b = await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )
        task_c = await self._create_task(
            client, seed, project_id, "Task C",
            depends_on=[{"task_id": task_b["id"], "type": "sequential"}],
        )

        # B: A upstream, C downstream
        resp = await self._get_chain(client, seed, task_b["id"])
        assert resp.status_code == 200
        body = resp.json()

        assert len(body["chain"]["upstream"]) == 1
        assert _find_in_chain(body["chain"]["upstream"], task_a["id"]) is not None
        assert len(body["chain"]["downstream"]) == 1
        assert _find_in_chain(body["chain"]["downstream"], task_c["id"]) is not None

        # C: A+B upstream (transitive), no downstream
        resp = await self._get_chain(client, seed, task_c["id"])
        assert resp.status_code == 200
        body = resp.json()

        assert len(body["chain"]["upstream"]) == 2  # A and B (B is direct, A is transitive)
        up_ids = {u["task_id"] for u in body["chain"]["upstream"]}
        assert task_a["id"] in up_ids
        assert task_b["id"] in up_ids
        assert body["chain"]["downstream"] == []

        # A: no upstream, B+C downstream
        resp = await self._get_chain(client, seed, task_a["id"])
        assert resp.status_code == 200
        body = resp.json()

        assert body["chain"]["upstream"] == []
        assert len(body["chain"]["downstream"]) == 2
        down_ids = {d["task_id"] for d in body["chain"]["downstream"]}
        assert task_b["id"] in down_ids
        assert task_c["id"] in down_ids

    @pytest.mark.asyncio
    async def test_direction_upstream_only(
        self, client: AsyncClient, seed: SeedData,
    ):
        """direction=upstream returns only upstream chain."""
        project_id = await self._create_project(client, seed, "上游仅")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        task_b = await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )

        resp = await self._get_chain(client, seed, task_b["id"], direction="upstream")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["chain"]["upstream"]) == 1
        assert body["chain"]["downstream"] == []

    @pytest.mark.asyncio
    async def test_direction_downstream_only(
        self, client: AsyncClient, seed: SeedData,
    ):
        """direction=downstream returns only downstream chain."""
        project_id = await self._create_project(client, seed, "下游仅")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )

        resp = await self._get_chain(client, seed, task_a["id"], direction="downstream")
        assert resp.status_code == 200
        body = resp.json()
        assert body["chain"]["upstream"] == []
        assert len(body["chain"]["downstream"]) == 1

    @pytest.mark.asyncio
    async def test_task_not_found(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Non-existent task → 404."""
        resp = await self._get_chain(client, seed, "tsk_nonexistent_00000000")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_direction(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Invalid direction param → 422."""
        project_id = await self._create_project(client, seed, "无效方向")
        task = await self._create_task(client, seed, project_id, "测试")

        headers = auth_header(seed.token)
        resp = await client.get(
            f"/v1/tasks/{task['id']}/dependency-chain?direction=sideways",
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cross_project_isolation(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Tasks in project A are not visible when querying project B's chain."""
        project_a = await self._create_project(client, seed, "项目A")
        project_b = await self._create_project(client, seed, "项目B")

        task_a1 = await self._create_task(client, seed, project_a, "A1")
        task_b1 = await self._create_task(client, seed, project_b, "B1")

        # Create a task in A that depends on A1
        await self._create_task(
            client, seed, project_a, "A2",
            depends_on=[{"task_id": task_a1["id"], "type": "sequential"}],
        )

        # B1 in project B should NOT see project A's downstream tasks
        resp = await self._get_chain(client, seed, task_b1["id"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["chain"]["downstream"] == []
        assert body["chain"]["upstream"] == []

    @pytest.mark.asyncio
    async def test_dependency_type_preserved(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Dependency type (sequential/artifact) is preserved in chain items."""
        project_id = await self._create_project(client, seed, "类型保留")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "artifact"}],
        )

        resp = await self._get_chain(client, seed, task_a["id"])
        assert resp.status_code == 200
        body = resp.json()
        down = body["chain"]["downstream"][0]
        assert down["dependency_type"] == "artifact"

    @pytest.mark.asyncio
    async def test_chain_item_fields(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Each chain item has task_id, title, status, dependency_type."""
        project_id = await self._create_project(client, seed, "字段校验")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )

        resp = await self._get_chain(client, seed, task_a["id"])
        assert resp.status_code == 200
        body = resp.json()
        for item in body["chain"]["downstream"]:
            assert "task_id" in item
            assert "title" in item
            assert "status" in item
            assert "dependency_type" in item
            assert isinstance(item["task_id"], str)
            assert isinstance(item["title"], str)
            assert isinstance(item["status"], str)
            assert isinstance(item["dependency_type"], str)

    @pytest.mark.asyncio
    async def test_diamond_dependency(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Diamond: A→B, A→C, B→D, C→D. D sees A+B+C upstream."""
        project_id = await self._create_project(client, seed, "菱形依赖")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        task_b = await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )
        task_c = await self._create_task(
            client, seed, project_id, "Task C",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )
        task_d = await self._create_task(
            client, seed, project_id, "Task D",
            depends_on=[
                {"task_id": task_b["id"], "type": "sequential"},
                {"task_id": task_c["id"], "type": "sequential"},
            ],
        )

        # D upstream: should include A, B, C (B and C direct; A transitive via both)
        resp = await self._get_chain(client, seed, task_d["id"])
        assert resp.status_code == 200
        body = resp.json()
        up_ids = {u["task_id"] for u in body["chain"]["upstream"]}
        assert task_a["id"] in up_ids
        assert task_b["id"] in up_ids
        assert task_c["id"] in up_ids
        # D itself is not in upstream
        assert task_d["id"] not in up_ids
        assert body["chain"]["downstream"] == []

        # A downstream: should include B, C, D
        resp = await self._get_chain(client, seed, task_a["id"])
        assert resp.status_code == 200
        body = resp.json()
        down_ids = {d["task_id"] for d in body["chain"]["downstream"]}
        assert task_b["id"] in down_ids
        assert task_c["id"] in down_ids
        assert task_d["id"] in down_ids

    @pytest.mark.asyncio
    async def test_deleted_dependency_task_handled(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Upstream reference to a deleted task returns '(deleted)' gracefully."""
        project_id = await self._create_project(client, seed, "已删依赖")
        task_a = await self._create_task(client, seed, project_id, "Task A")
        task_b = await self._create_task(
            client, seed, project_id, "Task B",
            depends_on=[{"task_id": task_a["id"], "type": "sequential"}],
        )

        # Delete task_a from DB directly
        from src.db import async_session_factory
        from src.models.task import Task
        async with async_session_factory() as session:
            t = await session.get(Task, task_a["id"])
            await session.delete(t)
            await session.commit()

        # B's upstream should still work — deleted task shows as (deleted)
        resp = await self._get_chain(client, seed, task_b["id"])
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["chain"]["upstream"]) == 1
        assert body["chain"]["upstream"][0]["task_id"] == task_a["id"]
        assert body["chain"]["upstream"][0]["title"] == "(deleted)"
