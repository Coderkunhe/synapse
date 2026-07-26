"""E2E 测试: Task depends_on 依赖校验 — P9-B6/B7。

覆盖:
- Claim 时依赖就绪检查（P9-B6）
- Create 时 depends_on 三段校验（P9-B7）
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ensure_project_role


def _uniq_slug(prefix: str) -> str:
    """生成唯一的项目 slug。"""
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestTaskDependencyCheck:
    """P9-B6: Task depends_on 依赖就绪检查。"""

    async def _setup_agent_and_task(
        self, client: AsyncClient, seed: SeedData,
        *, title: str = "任务", status: str = "ready",
        depends_on: list[dict] | None = None,
        project_id: str | None = None,
    ):
        """Helper: 注册 agent + 创建 task + 设为指定状态。

        若未提供 project_id 则自动创建新 Project（P9-B7：depends_on
        校验要求依赖 task 必须在同一 project 内，共享 project 时传入）。
        """
        headers = auth_header(seed.token)

        if project_id is None:
            proj_resp = await client.post(
                f"/v1/teams/{seed.team_id}/projects",
                json={"name": f"依赖测试-{title}", "slug": _uniq_slug("dep")},
                headers=headers,
            )
            project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": f"依赖测试Agent-{title}", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [{"name": "coding", "description": "编码"}],
                "supported_events": ["task.assigned"],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )

        # B56: claim requires builder project role
        await ensure_project_role(
            client, project_id, agent_id, "builder", headers,
        )

        task_body: dict = {
            "title": title,
            "description": "Verify task works correctly",
            "priority": "p1",
            "verifications": [{"type": "manual", "description": "Verification check passed"}],
        }
        if depends_on is not None:
            task_body["depends_on"] = depends_on

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json=task_body,
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        # Set to desired status via DB
        from src.db import async_session_factory
        from src.models.task import Task
        async with async_session_factory() as session:
            task = await session.get(Task, task_id)
            task.status = status
            task.version_no += 1
            version = task.version_no
            await session.commit()

        return project_id, agent_id, api_key, task_id, version

    async def _create_and_complete_task(
        self, client: AsyncClient, seed: SeedData, title: str,
        project_id: str | None = None,
    ) -> str:
        """Helper: 创建一个 completed 状态的任务，返回 task_id。"""
        _, _, _, task_id, _ = await self._setup_agent_and_task(
            client, seed, title=title, status="completed",
            project_id=project_id,
        )
        return task_id

    # ── P9-B6: Claim 时依赖就绪检查 ──────────────────────

    @pytest.mark.asyncio
    async def test_claim_blocked_by_unfinished_dependency(
        self, client: AsyncClient, seed: SeedData,
    ):
        """依赖未满足（依赖任务未完成）→ claim 返回 409。"""
        # 先创建共享 Project
        headers = auth_header(seed.token)
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "依赖测试-阻塞", "slug": _uniq_slug("dep-block")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 创建一个未完成的任务作为依赖
        _, _, _, dep_task_id, _ = await self._setup_agent_and_task(
            client, seed, title="依赖任务", status="in_progress",
            project_id=project_id,
        )

        # 创建依赖该任务的新任务
        _, _, api_key, task_id, version = await self._setup_agent_and_task(
            client, seed, title="被阻塞任务", status="ready",
            depends_on=[{"task_id": dep_task_id, "type": "sequential"}],
            project_id=project_id,
        )

        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            params={"expected_version": version},
            headers=auth_header(api_key),
        )
        assert claim_resp.status_code == 409
        error = claim_resp.json()["error"]
        assert error["code"] == "TASK_DEPENDENCY_NOT_READY"
        assert "in_progress" in error["message"]

    @pytest.mark.asyncio
    async def test_claim_allowed_when_dependencies_met(
        self, client: AsyncClient, seed: SeedData,
    ):
        """所有依赖已完成 → claim 成功。"""
        # 先创建共享 Project
        headers = auth_header(seed.token)
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "依赖测试-已满足", "slug": _uniq_slug("dep-met")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 创建一个已完成的任务作为依赖
        dep_task_id = await self._create_and_complete_task(
            client, seed, title="已完成依赖", project_id=project_id,
        )

        # 创建依赖该任务的新任务
        _, _, api_key, task_id, version = await self._setup_agent_and_task(
            client, seed, title="可认领任务", status="ready",
            depends_on=[{"task_id": dep_task_id, "type": "sequential"}],
            project_id=project_id,
        )

        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            params={"expected_version": version},
            headers=auth_header(api_key),
        )
        assert claim_resp.status_code == 200, claim_resp.text
        task = claim_resp.json()
        assert task["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_create_with_nonexistent_dependency(
        self, client: AsyncClient, seed: SeedData,
    ):
        """依赖任务不存在 → create 返回 404（P9-B7 前置到创建时校验）。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "依赖测试-404", "slug": _uniq_slug("dep-404")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "依赖不存在的任务",
                "description": "Verify task works correctly",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "Verification check passed"}],
                "depends_on": [{"task_id": "tsk_nonexistent", "type": "artifact"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 404, task_resp.text

    @pytest.mark.asyncio
    async def test_claim_normal_when_no_dependencies(
        self, client: AsyncClient, seed: SeedData,
    ):
        """无依赖任务 → claim 正常（不受 P9-B6 影响）。"""
        _, _, api_key, task_id, version = await self._setup_agent_and_task(
            client, seed, title="无依赖任务", status="ready",
        )

        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            params={"expected_version": version},
            headers=auth_header(api_key),
        )
        assert claim_resp.status_code == 200, claim_resp.text
        task = claim_resp.json()
        assert task["status"] == "in_progress"

    # ── P9-B7: create_task depends_on 校验 ──────────────────

    @pytest.mark.asyncio
    async def test_create_with_duplicate_dependency(
        self, client: AsyncClient, seed: SeedData,
    ):
        """重复依赖 ID → create 返回 409。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "依赖测试-重复", "slug": _uniq_slug("dep-dup")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 先创建一个 completed task 作为依赖
        dep_task_id = await self._create_and_complete_task(
            client, seed, title="重复依赖目标", project_id=project_id,
        )

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "重复依赖",
                "description": "Verify task works correctly",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "Verification check passed"}],
                "depends_on": [
                    {"task_id": dep_task_id, "type": "sequential"},
                    {"task_id": dep_task_id, "type": "artifact"},
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 409, task_resp.text
        assert task_resp.json()["error"]["code"] == "DUPLICATE_DEPENDENCY"

    @pytest.mark.asyncio
    async def test_create_with_cross_project_dependency(
        self, client: AsyncClient, seed: SeedData,
    ):
        """依赖任务跨 project → create 返回 409。"""
        headers = auth_header(seed.token)

        # 两个不同 Project
        proj1_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "依赖测试-跨项目A", "slug": _uniq_slug("dep-xproj-a")},
            headers=headers,
        )
        project_a = proj1_resp.json()["id"]

        proj2_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "依赖测试-跨项目B", "slug": _uniq_slug("dep-xproj-b")},
            headers=headers,
        )
        project_b = proj2_resp.json()["id"]

        # 在 project_a 中创建一个 completed task
        dep_task_id = await self._create_and_complete_task(
            client, seed, title="跨项目依赖目标", project_id=project_a,
        )

        # 在 project_b 中创建依赖 project_a 中 task 的任务 → 应失败
        task_resp = await client.post(
            f"/v1/projects/{project_b}/tasks",
            json={
                "title": "跨项目依赖",
                "description": "Verify task works correctly",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "Verification check passed"}],
                "depends_on": [{"task_id": dep_task_id, "type": "sequential"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 409, task_resp.text
        assert task_resp.json()["error"]["code"] == "DEPENDENCY_PROJECT_MISMATCH"

    @pytest.mark.asyncio
    async def test_create_with_circular_dependency(
        self, client: AsyncClient, seed: SeedData,
    ):
        """循环依赖 → create 返回 409。

        A depends_on B, B depends_on A → 应检测到循环。
        """
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "依赖测试-循环", "slug": _uniq_slug("dep-cycle")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 创建 task B（暂不设依赖）
        task_b_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Task B",
                "description": "Verify task works correctly",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "Verification check passed"}],
            },
            headers=headers,
        )
        assert task_b_resp.status_code == 201, task_b_resp.text
        task_b_id = task_b_resp.json()["id"]

        # 创建 task A，depends_on task B
        task_a_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Task A",
                "description": "Verify task works correctly",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "Verification check passed"}],
                "depends_on": [{"task_id": task_b_id, "type": "sequential"}],
            },
            headers=headers,
        )
        assert task_a_resp.status_code == 201, task_a_resp.text
        task_a_id = task_a_resp.json()["id"]

        # 通过 DB 直接给 task B 加 depends_on task A → B→A→B 循环形成
        from src.db import async_session_factory
        from src.models.task import Task
        from src.utils.json_utils import safe_dumps
        async with async_session_factory() as session:
            task_b = await session.get(Task, task_b_id)
            task_b.depends_on = safe_dumps([{"task_id": task_a_id, "type": "sequential"}])
            await session.commit()

        # 创建 task C depends_on task B — BFS 追溯 B 的依赖链应检测到 B→A→B 循环
        task_c_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Task C",
                "description": "Verify task works correctly",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "Verification check passed"}],
                "depends_on": [{"task_id": task_b_id, "type": "sequential"}],
            },
            headers=headers,
        )
        assert task_c_resp.status_code == 409, task_c_resp.text
        assert task_c_resp.json()["error"]["code"] == "CIRCULAR_DEPENDENCY"
