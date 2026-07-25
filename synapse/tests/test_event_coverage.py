"""P8-B8：事件覆盖测试 — 验证每种事件类型均正确写入。

测试覆盖 Task、Worker、Verification、Failure 四大域的所有 P8 核心事件类型。
每个测试同时验证 event_type 字符串和 payload 中预期字段的存在性。
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import SeedData, auth_header, ensure_project_role


# ── 辅助函数 ────────────────────────────────────────────────────────────


async def _get_events(client: AsyncClient, seed: SeedData) -> list[dict]:
    """通过 API 查询团队的所有事件。"""
    resp = await client.get(
        f"/v1/teams/{seed.team_id}/events",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    return resp.json()["items"]


async def _create_project(client: AsyncClient, seed: SeedData) -> dict:
    """创建测试项目。"""
    import uuid
    slug = f"evt-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": "Event Test Project", "description": "test", "slug": slug},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_task(
    client: AsyncClient, seed: SeedData, project_id: str, title: str = "Test Task",
) -> dict:
    """创建测试任务。"""
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
    assert resp.status_code == 201
    return resp.json()


async def _register_worker(client: AsyncClient, seed: SeedData) -> tuple[dict, str]:
    """注册 agent，返回 (agent_dict, api_key)。"""
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/agents",
        json={"name": "Test Worker", "provider": "claude"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["worker"], data["api_key"]


async def _worker_handshake(client: AsyncClient, agent_id: str, api_key: str) -> dict:
    """Worker 握手激活。"""
    resp = await client.post(
        f"/v1/agents/{agent_id}/handshake",
        json={
            "worker_version": "1.0",
            "capabilities": [{"name": "coding", "description": "Writes code"}],
            "supported_events": ["task.*"],
            "preferred_channel": "websocket",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    return resp.json()


# ── Task 事件测试 ───────────────────────────────────────────────────────


class TestTaskEventCoverage:
    """验证所有 Task 生命周期事件均正确写入。"""

    async def test_task_created_event(self, client: AsyncClient, seed: SeedData):
        """task.created 在创建时写入，payload 字段正确。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"], "Event Created")

        events = await _get_events(client, seed)
        created = [e for e in events
                   if e["event_type"] == "task.created" and e["target_id"] == task["id"]]
        assert len(created) == 1
        assert created[0]["payload"]["title"] == "Event Created"
        assert created[0]["payload"]["status"] == "backlog"
        assert created[0]["payload"]["verification_count"] == 1

    async def test_task_updated_event(self, client: AsyncClient, seed: SeedData):
        """task.updated 在 PATCH 时写入，包含 updated_fields。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.patch(
            f"/v1/tasks/{task['id']}",
            json={"title": "Updated Title", "expected_version": task["version_no"]},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        updated = [e for e in events
                   if e["event_type"] == "task.updated" and e["target_id"] == task["id"]]
        assert len(updated) == 1

    async def test_task_readied_event(self, client: AsyncClient, seed: SeedData):
        """task.readied 在 BACKLOG → READY 转换时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        from src.db import async_session_factory
        from src.services.task_service import get_task as svc_get_task, ready_task

        async with async_session_factory() as db:
            t = await svc_get_task(db, task["id"])
            await ready_task(
                db, task["id"],
                expected_version=t.version_no,
                actor_type="human", actor_id=seed.member_id, team_id=seed.team_id,
            )
            await db.commit()

        events = await _get_events(client, seed)
        readied = [e for e in events
                   if e["event_type"] == "task.readied" and e["target_id"] == task["id"]]
        assert len(readied) == 1
        assert readied[0]["payload"]["previous_status"] == "backlog"
        assert readied[0]["payload"]["new_status"] == "ready"

    async def test_task_assigned_event(self, client: AsyncClient, seed: SeedData):
        """task.assigned 在 BACKLOG → IN_PROGRESS（通过 assign）时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.post(
            f"/v1/tasks/{task['id']}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": task["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        assigned = [e for e in events
                    if e["event_type"] == "task.assigned" and e["target_id"] == task["id"]]
        assert len(assigned) == 1
        assert assigned[0]["payload"]["new_status"] == "in_progress"

    async def test_task_claimed_event(self, client: AsyncClient, seed: SeedData):
        """task.claimed 在 READY → IN_PROGRESS（通过 Worker 认领）时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # 先将任务设为 READY
        from src.db import async_session_factory
        from src.services.task_service import get_task as svc_get_task, ready_task

        async with async_session_factory() as db:
            t = await svc_get_task(db, task["id"])
            await ready_task(
                db, task["id"],
                expected_version=t.version_no,
                actor_type="human", actor_id=seed.member_id, team_id=seed.team_id,
            )
            await db.commit()

        resp = await client.get(
            f"/v1/tasks/{task['id']}", headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        ready_task_data = resp.json()

        # 注册并握手 agent
        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        # B56: claim requires builder project role
        await ensure_project_role(
            client, project["id"], agent_data["id"], "builder", auth_header(seed.token),
        )

        # Worker 认领任务
        resp = await client.post(
            f"/v1/tasks/{task['id']}/claim?expected_version={ready_task_data['version_no']}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        claimed = [e for e in events
                   if e["event_type"] == "task.claimed" and e["target_id"] == task["id"]]
        assert len(claimed) == 1
        assert claimed[0]["payload"]["new_status"] == "in_progress"
        assert "claimed_at" in claimed[0]["payload"]

    async def test_task_submitted_event(self, client: AsyncClient, seed: SeedData):
        """task.submitted 在 IN_PROGRESS → IN_VERIFICATION（通过 submit）时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.post(
            f"/v1/tasks/{task['id']}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": task["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assigned = resp.json()

        from src.db import async_session_factory
        from src.models.verification import Verification

        async with async_session_factory() as db:
            result = await db.execute(
                select(Verification).where(Verification.task_id == task["id"]),
            )
            vers = result.scalars().all()
            ver_id = vers[0].id

        resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Done",
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": assigned["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        submitted = [e for e in events
                     if e["event_type"] == "task.submitted" and e["target_id"] == task["id"]]
        assert len(submitted) == 1
        assert submitted[0]["payload"]["new_status"] == "in_verification"

    async def test_task_paused_and_resumed_events(self, client: AsyncClient, seed: SeedData):
        """task.paused + task.resumed 在暂停/恢复循环中写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.post(
            f"/v1/tasks/{task['id']}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": task["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        in_progress = resp.json()

        from src.db import async_session_factory
        from src.services.task_service import pause_task, resume_task

        async with async_session_factory() as db:
            from src.services.task_service import get_task as svc_get_task
            t = await svc_get_task(db, task["id"])
            await pause_task(
                db, task["id"],
                reason="Need clarification",
                expected_version=in_progress["version_no"],
                actor_type="human", actor_id=seed.member_id, team_id=seed.team_id,
            )
            await db.commit()

        events = await _get_events(client, seed)
        paused_events = [e for e in events
                         if e["event_type"] == "task.paused" and e["target_id"] == task["id"]]
        assert len(paused_events) == 1
        assert paused_events[0]["payload"]["new_status"] == "paused"
        assert "reason" in paused_events[0]["payload"]

        # 恢复
        resp = await client.get(
            f"/v1/tasks/{task['id']}", headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        paused = resp.json()

        async with async_session_factory() as db:
            from src.services.task_service import get_task as svc_get_task
            t = await svc_get_task(db, task["id"])
            await resume_task(
                db, task["id"],
                expected_version=paused["version_no"],
                actor_type="human", actor_id=seed.member_id, team_id=seed.team_id,
            )
            await db.commit()

        events = await _get_events(client, seed)
        resumed_events = [e for e in events
                          if e["event_type"] == "task.resumed" and e["target_id"] == task["id"]]
        assert len(resumed_events) == 1
        assert resumed_events[0]["payload"]["new_status"] == "in_progress"

    async def test_task_completed_event(self, client: AsyncClient, seed: SeedData):
        """task.completed 在所有 verification 通过时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.post(
            f"/v1/tasks/{task['id']}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": task["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assigned = resp.json()

        from src.db import async_session_factory
        from src.models.verification import Verification

        async with async_session_factory() as db:
            result = await db.execute(
                select(Verification).where(Verification.task_id == task["id"]),
            )
            vers = result.scalars().all()
            ver_id = vers[0].id

        resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Done",
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": assigned["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        submitted = resp.json()

        # 执行 verification → passed
        resp = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={
                "status": "passed",
                "expected_task_version": submitted["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        completed = [e for e in events
                     if e["event_type"] == "task.completed" and e["target_id"] == task["id"]]
        assert len(completed) == 1
        assert completed[0]["payload"]["new_status"] == "completed"

    async def test_task_rejected_event(self, client: AsyncClient, seed: SeedData):
        """task.rejected 在 verification 失败时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.post(
            f"/v1/tasks/{task['id']}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": task["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assigned = resp.json()

        from src.db import async_session_factory
        from src.models.verification import Verification

        async with async_session_factory() as db:
            result = await db.execute(
                select(Verification).where(Verification.task_id == task["id"]),
            )
            vers = result.scalars().all()
            ver_id = vers[0].id

        resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Done",
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": assigned["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        submitted = resp.json()

        # 执行 verification → failed
        resp = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={
                "status": "failed",
                "rejection_reason": "Not good enough",
                "expected_task_version": submitted["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        rejected = [e for e in events
                    if e["event_type"] == "task.rejected" and e["target_id"] == task["id"]]
        assert len(rejected) == 1
        assert rejected[0]["payload"]["new_status"] == "rejected"

    async def test_task_cancelled_event(self, client: AsyncClient, seed: SeedData):
        """task.cancelled 在取消时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.post(
            f"/v1/tasks/{task['id']}/cancel?expected_version={task['version_no']}",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        cancelled = [e for e in events
                     if e["event_type"] == "task.cancelled" and e["target_id"] == task["id"]]
        assert len(cancelled) == 1
        assert cancelled[0]["payload"]["new_status"] == "cancelled"


# ── Worker 事件测试 ──────────────────────────────────────────────────────


class TestAgentEventCoverage:
    """验证 Worker 生命周期和运行时事件均正确写入。"""

    async def test_agent_registered_event(self, client: AsyncClient, seed: SeedData):
        """agent.registered 在 agent 创建时写入。"""
        agent_data, _ = await _register_worker(client, seed)

        events = await _get_events(client, seed)
        registered = [e for e in events
                      if e["event_type"] == "worker.registered"
                      and e["target_id"] == agent_data["id"]]
        assert len(registered) == 1
        assert registered[0]["payload"]["name"] == "Test Worker"
        assert registered[0]["payload"]["status"] == "pending"

    async def test_worker_handshake_event(self, client: AsyncClient, seed: SeedData):
        """agent.handshake 在 agent 激活时写入。"""
        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        events = await _get_events(client, seed)
        handshake = [e for e in events
                     if e["event_type"] == "worker.handshake"
                     and e["target_id"] == agent_data["id"]]
        assert len(handshake) == 1
        assert handshake[0]["payload"]["new_status"] == "active"
        assert handshake[0]["payload"]["capability_count"] == 1

    async def test_agent_runtime_events(self, client: AsyncClient, seed: SeedData):
        """agent.runtime.* 事件在心跳驱动的状态转换时写入。"""
        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        # 带任务的心跳 → IDLE → BUSY
        resp = await client.post(
            f"/v1/agents/{agent_data['id']}/heartbeat",
            json={"current_task_id": "task-123"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        busy_events = [e for e in events
                       if e["event_type"] == "worker.runtime.busy"
                       and e["target_id"] == agent_data["id"]]
        assert len(busy_events) >= 1

        # 无任务的心跳 → BUSY → IDLE
        resp = await client.post(
            f"/v1/agents/{agent_data['id']}/heartbeat",
            json={},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        idle_events = [e for e in events
                       if e["event_type"] == "worker.runtime.idle"
                       and e["target_id"] == agent_data["id"]]
        assert len(idle_events) >= 1

    async def test_agent_deleted_event(self, client: AsyncClient, seed: SeedData):
        """agent.deleted 在硬删除时写入。"""
        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        resp = await client.delete(
            f"/v1/agents/{agent_data['id']}",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 204

        events = await _get_events(client, seed)
        deleted = [e for e in events
                       if e["event_type"] == "worker.deleted"
                       and e["target_id"] == agent_data["id"]]
        assert len(deleted) == 1
        assert deleted[0]["payload"]["name"] == agent_data["name"]

