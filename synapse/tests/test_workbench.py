"""个人工作台端点测试: GET /v1/me/tasks — 跨项目聚合「我的任务」+ dependency_blocked。

P17-B29: 人侧上下文卸载第三刀（项目 B5/B6 → 团队 B27/B28 → 个人 B29）。
覆盖两条 owner 路径（claim 写 human+worker_id · assign 写 member+member_id）、
dependency_blocked 标志、跨项目聚合、负对照。
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestWorkbenchMyTasks:
    """P17-B29: GET /me/tasks 的「我的任务」聚合语义。"""

    async def _create_project(self, client: AsyncClient, seed: SeedData, name: str) -> str:
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": name, "slug": _uniq_slug("wb")},
            headers=auth_header(seed.token),
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
    ) -> str:
        """创建 task 并直接 DB 写 owner/status（绕过 claim/ready 端点的 role/version 复杂度）。"""
        body: dict = {
            "title": title,
            "description": "Test task",
            "priority": "p1",
            "verifications": [{"type": "manual", "description": "Verification check passed successfully"}],
        }
        if depends_on is not None:
            body["depends_on"] = depends_on
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json=body,
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    async def _set_owner(self, task_id: str, *, owner_type: str, owner_id: str, status: str):
        """直接 DB 写 owner_type/owner_id/status。"""
        from src.db import async_session_factory
        from src.models.task import Task
        async with async_session_factory() as session:
            task = await session.get(Task, task_id)
            task.owner_type = owner_type
            task.owner_id = owner_id
            task.status = status
            await session.commit()

    def _find_task(self, body: dict, task_id: str) -> dict | None:
        for t in body["tasks"]:
            if t["task_id"] == task_id:
                return t
        return None

    # ── tests ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_human_claim_task_returned(self, client: AsyncClient, seed: SeedData):
        """claim 路径（owner_type=human + owner_id=derived worker_id）→ 命中 + project_name。"""
        project_id = await self._create_project(client, seed, "我的项目")
        task_id = await self._create_task(client, seed, project_id, "我认领的任务")
        await self._set_owner(task_id, owner_type="human", owner_id=seed.worker_id, status="in_progress")

        resp = await client.get("/v1/me/tasks", headers=auth_header(seed.token))
        assert resp.status_code == 200, resp.text
        t = self._find_task(resp.json(), task_id)
        assert t is not None, f"task {task_id} 未出现在我的任务中: {resp.json()}"
        assert t["status"] == "in_progress"
        assert t["project_id"] == project_id
        assert t["project_name"] is not None
        assert t["dependency_blocked"] is False  # in_progress 不算 blocked

    @pytest.mark.asyncio
    async def test_member_assign_task_returned(self, client: AsyncClient, seed: SeedData):
        """assign 路径（owner_type=member + owner_id=member.id）→ 经 user_id 反查命中。"""
        project_id = await self._create_project(client, seed, "被分配项目")
        task_id = await self._create_task(client, seed, project_id, "被分配给我的任务")
        await self._set_owner(task_id, owner_type="member", owner_id=seed.member_id, status="in_progress")

        resp = await client.get("/v1/me/tasks", headers=auth_header(seed.token))
        assert resp.status_code == 200, resp.text
        assert self._find_task(resp.json(), task_id) is not None

    @pytest.mark.asyncio
    async def test_other_owner_not_returned(self, client: AsyncClient, seed: SeedData):
        """负对照：他人名下的任务不出现在「我的任务」。"""
        project_id = await self._create_project(client, seed, "他人项目")
        task_id = await self._create_task(client, seed, project_id, "别人的任务")
        await self._set_owner(task_id, owner_type="worker", owner_id="wrk_someone_else", status="in_progress")

        resp = await client.get("/v1/me/tasks", headers=auth_header(seed.token))
        assert resp.status_code == 200, resp.text
        assert self._find_task(resp.json(), task_id) is None

    @pytest.mark.asyncio
    async def test_dependency_blocked_flag(self, client: AsyncClient, seed: SeedData):
        """我的 ready 任务：depends_on 未完成 → blocked=True；已满足 → False。"""
        project_id = await self._create_project(client, seed, "依赖项目")
        dep_unmet = await self._create_task(client, seed, project_id, "未完成依赖")
        dep_met = await self._create_task(client, seed, project_id, "已完成依赖")
        blocked_id = await self._create_task(
            client, seed, project_id, "被阻塞", depends_on=[{"task_id": dep_unmet, "type": "sequential"}],
        )
        met_id = await self._create_task(
            client, seed, project_id, "依赖已满足",
            depends_on=[{"task_id": dep_met, "type": "sequential"}],
        )

        from src.db import async_session_factory
        from src.models.task import Task
        async with async_session_factory() as session:
            for tid, status in (
                (dep_unmet, "backlog"),   # 未完成 → blocked_id 应 blocked
                (dep_met, "completed"),   # 已完成 → met_id 应 unblocked
                (blocked_id, "ready"),
                (met_id, "ready"),
            ):
                task = await session.get(Task, tid)
                task.owner_type = "human"
                task.owner_id = seed.worker_id
                task.status = status
            await session.commit()

        resp = await client.get("/v1/me/tasks", headers=auth_header(seed.token))
        assert resp.status_code == 200, resp.text
        assert self._find_task(resp.json(), blocked_id)["dependency_blocked"] is True
        assert self._find_task(resp.json(), met_id)["dependency_blocked"] is False

    @pytest.mark.asyncio
    async def test_cross_project_aggregation(self, client: AsyncClient, seed: SeedData):
        """跨项目：两个项目的我的任务都出现。"""
        p1 = await self._create_project(client, seed, "项目甲")
        p2 = await self._create_project(client, seed, "项目乙")
        t1 = await self._create_task(client, seed, p1, "甲任务")
        t2 = await self._create_task(client, seed, p2, "乙任务")
        await self._set_owner(t1, owner_type="human", owner_id=seed.worker_id, status="in_progress")
        await self._set_owner(t2, owner_type="human", owner_id=seed.worker_id, status="ready")

        resp = await client.get("/v1/me/tasks", headers=auth_header(seed.token))
        assert resp.status_code == 200, resp.text
        ids = {t["task_id"] for t in resp.json()["tasks"]}
        assert {t1, t2} <= ids
