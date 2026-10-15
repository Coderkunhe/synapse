"""E2E 测试: GET /v1/dashboard/teams/{team_id}/projects-breakdown — dependency_blocked 叠加字段。

P17-B27: 团队级「态势」视图 blocked 信号——``dependency_blocked`` = ready 状态中
``depends_on`` 引用未全部 COMPLETED 的任务数（叠加非改写，ready 计数保持总 ready）。
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestProjectsBreakdownBlocked:
    """P17-B27: projects-breakdown 的 dependency_blocked 叠加字段。"""

    async def _create_project(self, client: AsyncClient, seed: SeedData, name: str) -> str:
        headers = auth_header(seed.token)
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": name, "slug": _uniq_slug("b27")},
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
        status: str = "backlog",
        depends_on: list[dict] | None = None,
    ) -> str:
        """创建 task 并直接 DB 写 status（避免 /ready 端点需 role/version 的复杂度）。"""
        headers = auth_header(seed.token)
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
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        task_id = resp.json()["id"]

        from src.db import async_session_factory
        from src.models.task import Task
        async with async_session_factory() as session:
            task = await session.get(Task, task_id)
            task.status = status
            await session.commit()
        return task_id

    @staticmethod
    def _find_project(body: dict, project_id: str) -> dict | None:
        for p in body["projects"]:
            if p["project_id"] == project_id:
                return p
        return None

    # ── tests ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_blocked_ready_task_counted(self, client: AsyncClient, seed: SeedData):
        """ready 且 depends_on 未完成 → dependency_blocked==1，ready 计数仍含它（叠加语义）。"""
        project_id = await self._create_project(client, seed, "阻塞项目")

        dep_id = await self._create_task(client, seed, project_id, "依赖任务", status="backlog")
        await self._create_task(
            client, seed, project_id, "被阻塞任务", status="ready",
            depends_on=[{"task_id": dep_id, "type": "sequential"}],
        )
        await self._create_task(client, seed, project_id, "自由任务", status="ready")

        resp = await client.get(
            f"/v1/dashboard/teams/{seed.team_id}/projects-breakdown",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        p = self._find_project(resp.json(), project_id)
        assert p is not None
        assert p["dependency_blocked"] == 1
        assert p["by_status"]["ready"] == 2  # 叠加：blocked 仍计入 ready
        assert p["by_status"]["backlog"] == 1

    @pytest.mark.asyncio
    async def test_dependency_met_not_blocked(self, client: AsyncClient, seed: SeedData):
        """ready 且 depends_on 已全部 COMPLETED → dependency_blocked==0。"""
        project_id = await self._create_project(client, seed, "依赖已满足")
        dep_id = await self._create_task(client, seed, project_id, "依赖任务", status="completed")
        await self._create_task(
            client, seed, project_id, "就绪任务", status="ready",
            depends_on=[{"task_id": dep_id, "type": "sequential"}],
        )

        resp = await client.get(
            f"/v1/dashboard/teams/{seed.team_id}/projects-breakdown",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        p = self._find_project(resp.json(), project_id)
        assert p is not None
        assert p["dependency_blocked"] == 0
        assert p["by_status"]["ready"] == 1

    @pytest.mark.asyncio
    async def test_no_ready_tasks_zero_blocked(self, client: AsyncClient, seed: SeedData):
        """无 ready 任务 → dependency_blocked==0（默认值，非缺失）。"""
        project_id = await self._create_project(client, seed, "空项目")
        await self._create_task(client, seed, project_id, "仅 backlog", status="backlog")

        resp = await client.get(
            f"/v1/dashboard/teams/{seed.team_id}/projects-breakdown",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        p = self._find_project(resp.json(), project_id)
        assert p is not None
        assert p["dependency_blocked"] == 0
        assert p["by_status"]["ready"] == 0
