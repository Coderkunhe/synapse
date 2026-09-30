"""P100-B176：任务事件流端点 + actor_type 读取侧 coerce 容错。

覆盖两条缺陷：
- PFL-269：event.actor_type 遗留脏值（agent/member/SYSTEM）→ 读取侧 coerce，
  端点不再 500，单条脏值不拖垮整个事件流。
- PFL-272：/tasks/{id}/events 实体级端点，过滤下推 SQL WHERE（非前端 filter）。
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


# ── 辅助函数 ────────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, seed: SeedData) -> dict:
    slug = f"te-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": "Task Events Test", "description": "test", "slug": slug},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_task(
    client: AsyncClient, seed: SeedData, project_id: str, title: str,
) -> dict:
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={
            "title": title,
            "description": "Test description",
            "priority": "p2",
            "verifications": [{"type": "manual", "description": "Check output"}],
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_second_team_token() -> str:
    """创建第二个 team 及其 admin token（用于跨 team 越权断言）。"""
    from src.auth import create_access_token
    from src.constants import WorkerActorType, WorkerStatus
    from src.db import async_session_factory
    from src.models.member import Member
    from src.models.team import Team
    from src.models.worker import Worker
    from src.utils.id_gen import derive_id, generate_id

    team_id = generate_id("team")
    member_id = generate_id("member")
    worker_id = derive_id(member_id, "worker")
    async with async_session_factory() as session:
        short = team_id.replace("tea_", "")[-12:]
        session.add_all([
            Team(id=team_id, name=f"Test Team {short}", slug=f"test-{short}"),
            Member(
                id=member_id, team_id=team_id,
                user_id=f"user-{member_id[:8]}", display_name="Admin", role="admin",
            ),
            Worker(
                id=worker_id, name="Admin", team_id=team_id, user_id=None,
                actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE,
            ),
        ])
        await session.commit()

    return create_access_token(
        user_id=f"user-{member_id[:8]}",
        actor_id=worker_id,
        team_id=team_id,
        role="admin",
    )


# ── PFL-269：actor_type coerce ──────────────────────────────────────────


class TestActorTypeCoerce:
    async def test_team_events_coerces_legacy_actor_type(self, client: AsyncClient, seed: SeedData):
        """脏 actor_type 不再 500，读取侧归一为合法枚举值。"""
        from src.db import async_session_factory
        from src.services.event_store import event_store

        expected = {
            "agent": "worker",
            "member": "human",
            "SYSTEM": "system",
            "bogus_value": "system",  # 未知值 fallback system
        }
        target_id = "task-legacy-target"
        async with async_session_factory() as db:
            for raw in expected:
                await event_store.record(
                    db,
                    event_type="test.legacy_actor",
                    team_id=seed.team_id,
                    actor_type=raw,
                    actor_id="legacy-actor",
                    target_type="task",
                    target_id=target_id,
                    payload={"raw": raw},
                )
            await db.commit()

        resp = await client.get(
            f"/v1/teams/{seed.team_id}/events", headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text  # 关键：不再 500

        items = [e for e in resp.json()["items"] if e["event_type"] == "test.legacy_actor"]
        assert len(items) == 4
        got = {e["payload"]["raw"]: e["actor_type"] for e in items}
        for raw, coerced in expected.items():
            assert got[raw] == coerced, f"{raw} 应归一为 {coerced}，实为 {got.get(raw)}"


# ── PFL-272：/tasks/{id}/events 实体级端点 ──────────────────────────────


class TestTaskEventsEndpoint:
    async def test_task_events_filtered_to_single_task(self, client: AsyncClient, seed: SeedData):
        """查询层下推：只返回本 task 的事件，不混入其他 task / 其他实体。"""
        project = await _create_project(client, seed)
        task_a = await _create_task(client, seed, project["id"], "Task A")
        task_b = await _create_task(client, seed, project["id"], "Task B")

        resp_a = await client.get(
            f"/v1/tasks/{task_a['id']}/events", headers=auth_header(seed.token),
        )
        assert resp_a.status_code == 200, resp_a.text
        items_a = resp_a.json()["items"]
        # 本 task 的创建事件在场（此前 team 级 + 前端 filter 会挤掉）
        assert any(e["event_type"] == "task.created" for e in items_a)
        # 全部命中本 task（查询层下推，非前端过滤）
        assert all(e["target_id"] == task_a["id"] for e in items_a)

        resp_b = await client.get(
            f"/v1/tasks/{task_b['id']}/events", headers=auth_header(seed.token),
        )
        assert resp_b.status_code == 200, resp_b.text
        items_b = resp_b.json()["items"]
        assert all(e["target_id"] == task_b["id"] for e in items_b)
        # A 的事件绝不泄漏进 B 的事件流
        assert not any(e["target_id"] == task_a["id"] for e in items_b)

    async def test_task_events_cross_team_404(self, client: AsyncClient, seed: SeedData):
        """跨 team 访问任务事件流 → 404（不泄露存在性）。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"], "Secret Task")

        other_token = await _make_second_team_token()
        resp = await client.get(
            f"/v1/tasks/{task['id']}/events", headers=auth_header(other_token),
        )
        assert resp.status_code == 404, resp.text

    async def test_task_events_unknown_task_404(self, client: AsyncClient, seed: SeedData):
        """不存在的 task → 404。"""
        resp = await client.get(
            "/v1/tasks/task-nonexistent/events", headers=auth_header(seed.token),
        )
        assert resp.status_code == 404, resp.text
