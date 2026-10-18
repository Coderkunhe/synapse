"""P17-B38 服务端过滤回归 — unclaimed / mine / multi-status。

验证 list_tasks 新增的三个服务端过滤：
- unclaimed=true 只回 ready + 无主
- mine=true 双路径 owner 命中（claim derived worker_id + assign member.id）
- status=completed,cancelled 多值过滤 + total 精确
- 回归：单 status / overdue / 无过滤行为不变
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


async def _create_project(client: AsyncClient, seed: SeedData, name: str) -> str:
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": name, "slug": _uniq_slug("p38")},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_task(
    client: AsyncClient,
    seed: SeedData,
    project_id: str,
    title: str,
    *,
    status: str = "backlog",
    owner_id: str | None = None,
    owner_type: str | None = None,
    deadline_at: str | None = None,
) -> str:
    """API 创建 Task 后直接 DB 写 status/owner/deadline（避免端点状态机复杂度）。"""
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={
            "title": title,
            "description": "P17-B38 filter test",
            "priority": "p1",
            "verifications": [{"type": "manual", "description": "Verification check passed successfully"}],
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]

    from datetime import datetime
    from src.db import async_session_factory
    from src.models.task import Task

    async with async_session_factory() as session:
        task = await session.get(Task, task_id)
        task.status = status
        task.owner_id = owner_id
        task.owner_type = owner_type
        if deadline_at is not None:
            task.deadline_at = datetime.fromisoformat(deadline_at)
        await session.commit()
    return task_id


class TestTaskQueryFilters:
    @pytest.mark.asyncio
    async def test_unclaimed_true_only_ready_unowned(self, client: AsyncClient, seed: SeedData):
        """unclaimed=true 只回 ready+无主，排除 ready+已 assign、backlog。"""
        project_id = await _create_project(client, seed, "Unclaimed Filter")

        wanted = await _create_task(client, seed, project_id, "ready unowned", status="ready")
        await _create_task(client, seed, project_id, "ready owned", status="ready", owner_id="worker-other", owner_type="worker")
        await _create_task(client, seed, project_id, "backlog", status="backlog")
        await _create_task(client, seed, project_id, "completed", status="completed")

        resp = await client.get(
            f"/v1/projects/{project_id}/tasks",
            params={"unclaimed": "true"},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert [t["id"] for t in body["items"]] == [wanted]

    @pytest.mark.asyncio
    async def test_mine_true_matches_claim_and_assign_paths(self, client: AsyncClient, seed: SeedData):
        """mine=true 双路径命中：claim（derived worker_id）与 assign（member.id）。"""
        project_id = await _create_project(client, seed, "Mine Filter")

        claim_task = await _create_task(
            client, seed, project_id, "claim path",
            status="in_progress", owner_id=seed.worker_id, owner_type="human",
        )
        assign_task = await _create_task(
            client, seed, project_id, "assign path",
            status="in_progress", owner_id=seed.member_id, owner_type="member",
        )
        await _create_task(
            client, seed, project_id, "someone else",
            status="in_progress", owner_id="worker-other", owner_type="worker",
        )
        await _create_task(client, seed, project_id, "unowned", status="ready")

        resp = await client.get(
            f"/v1/projects/{project_id}/tasks",
            params={"mine": "true"},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        got = {t["id"] for t in body["items"]}
        assert got == {claim_task, assign_task}
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_status_comma_separated_multi_values(self, client: AsyncClient, seed: SeedData):
        """status=completed,cancelled 只回两状态且 total 精确。"""
        project_id = await _create_project(client, seed, "Multi Status")

        completed = await _create_task(client, seed, project_id, "completed one", status="completed")
        cancelled = await _create_task(client, seed, project_id, "cancelled one", status="cancelled")
        await _create_task(client, seed, project_id, "ready one", status="ready")
        await _create_task(client, seed, project_id, "backlog one", status="backlog")

        resp = await client.get(
            f"/v1/projects/{project_id}/tasks",
            params={"status": "completed,cancelled"},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        got = {t["id"] for t in body["items"]}
        assert got == {completed, cancelled}

    @pytest.mark.asyncio
    async def test_regression_single_status_overdue_no_filter(self, client: AsyncClient, seed: SeedData):
        """回归：单 status / overdue / 无过滤行为不变。"""
        project_id = await _create_project(client, seed, "Regression")

        ready_task = await _create_task(client, seed, project_id, "ready one", status="ready")
        overdue_task = await _create_task(
            client, seed, project_id, "overdue ready", status="ready",
            deadline_at="2020-01-01T00:00:00",
        )
        completed_task = await _create_task(client, seed, project_id, "completed overdue", status="completed", deadline_at="2020-01-01T00:00:00")

        # 单 status
        resp = await client.get(
            f"/v1/projects/{project_id}/tasks",
            params={"status": "ready"},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {t["id"] for t in body["items"]} == {ready_task, overdue_task}
        assert body["total"] == 2

        # overdue 排除 completed
        resp = await client.get(
            f"/v1/projects/{project_id}/tasks",
            params={"status": "overdue"},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [t["id"] for t in body["items"]] == [overdue_task]
        assert body["total"] == 1

        # 无过滤
        resp = await client.get(
            f"/v1/projects/{project_id}/tasks",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 3
        assert {t["id"] for t in body["items"]} == {ready_task, overdue_task, completed_task}
