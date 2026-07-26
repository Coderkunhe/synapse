"""P8-B9：Gate + Signal 测试 — 批量创建、终止、批次完成、WS 信号。

测试覆盖 B9 中引入的三项新能力：
  1. 批量任务创建（D-P7-023：Creator 批量操作）
  2. 任务终止（I2 基础形态）
  3. 批次完成事件（所有任务到达终态时触发 batch.completed）
  4. WS 信号验证（关键事件类型到达订阅者）
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


# ── 辅助函数 ──────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, seed: SeedData, slug: str = "") -> dict:
    import uuid

    s = slug or f"b9-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": "B9 Test Project", "description": "Verify task works correctly", "slug": s},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_batch(
    client: AsyncClient, seed: SeedData, project_id: str,
) -> dict:
    resp = await client.post(
        f"/v1/projects/{project_id}/batches",
        json={"name": "B9 Test Batch", "description": "batch completion tests"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_task(
    client: AsyncClient, seed: SeedData, project_id: str,
    title: str = "Test Task", batch_id: str | None = None,
) -> dict:
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={
            "title": title,
            "description": "Test description",
            "priority": "p2",
            "batch_id": batch_id,
            "verifications": [{"type": "manual", "description": "Check output"}],
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    return resp.json()


async def _get_events(client: AsyncClient, seed: SeedData) -> list[dict]:
    resp = await client.get(
        f"/v1/teams/{seed.team_id}/events",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    return resp.json()["items"]


async def _register_worker(client: AsyncClient, seed: SeedData) -> tuple[dict, str]:
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/agents",
        json={"name": "Test Worker", "provider": "claude"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["worker"], data["api_key"]


async def _worker_handshake(client: AsyncClient, agent_id: str, api_key: str) -> dict:
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


# ── 批量任务创建 ──────────────────────────────────────────────────────


class TestBatchTaskCreate:
    """批量任务创建端点（P8-B9，D-P7-023）。"""

    async def test_create_batch_success(self, client: AsyncClient, seed: SeedData):
        """批量创建 3 个任务 — 全部成功，状态为 backlog。"""
        project = await _create_project(client, seed)

        resp = await client.post(
            f"/v1/projects/{project['id']}/tasks/batch",
            json={
                "tasks": [
                    {
                        "title": "Task 1",
                        "description": "First task",
                        "priority": "p1",
                        "verifications": [{"type": "manual", "description": "Check condition one"}],
                    },
                    {
                        "title": "Task 2",
                        "description": "Second task",
                        "priority": "p2",
                        "verifications": [{"type": "manual", "description": "Check condition two"}],
                    },
                    {
                        "title": "Task 3",
                        "description": "Third task",
                        "priority": "p3",
                        "verifications": [
                            {"type": "manual", "description": "Check condition three A"},
                            {"type": "check_list", "description": "Check condition three B"},
                        ],
                    },
                ]
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 3
        assert all(t["status"] == "backlog" for t in data)
        assert data[0]["title"] == "Task 1"
        assert data[1]["title"] == "Task 2"
        assert data[2]["title"] == "Task 3"

        # 验证事件已记录
        events = await _get_events(client, seed)
        created_events = [e for e in events if e["event_type"] == "task.created"]
        assert len(created_events) == 3

    async def test_create_batch_single_task(self, client: AsyncClient, seed: SeedData):
        """批量创建 1 个任务正常工作（边界：min_length=1）。"""
        project = await _create_project(client, seed)

        resp = await client.post(
            f"/v1/projects/{project['id']}/tasks/batch",
            json={
                "tasks": [
                    {
                        "title": "Solo Task",
                        "description": "Just one",
                        "verifications": [{"type": "manual", "description": "Check verification works correctly"}],
                    },
                ]
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Solo Task"

    async def test_create_batch_empty_list(self, client: AsyncClient, seed: SeedData):
        """空 tasks 数组返回 422。"""
        project = await _create_project(client, seed)

        resp = await client.post(
            f"/v1/projects/{project['id']}/tasks/batch",
            json={"tasks": []},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 422

    async def test_create_batch_exceeds_limit(self, client: AsyncClient, seed: SeedData):
        """提交 >20 个任务时返回 422。"""
        project = await _create_project(client, seed)

        resp = await client.post(
            f"/v1/projects/{project['id']}/tasks/batch",
            json={
                "tasks": [
                    {
                        "title": f"T{i}",
                        "description": "Task description here",
                        "verifications": [{"type": "manual", "description": "Verification check C"}],
                    }
                    for i in range(21)
                ]
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 422

    async def test_create_batch_atomic_validation(
        self, client: AsyncClient, seed: SeedData,
    ):
        """P9-B69: 如果有一个任务缺少 description，整个批次被拒绝。"""
        project = await _create_project(client, seed)

        resp = await client.post(
            f"/v1/projects/{project['id']}/tasks/batch",
            json={
                "tasks": [
                    {
                        "title": "Valid Task",
                        "description": "Task description here",
                        "verifications": [{"type": "manual", "description": "Verification check V"}],
                    },
                    {
                        "title": "Invalid Task",
                        "description": "",  # <-- 无效：description 现在 required
                    },
                ]
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code in (409, 422), f"期望 409 或 422，实际 {resp.status_code}"

        # 验证没有任务被创建
        resp2 = await client.get(
            f"/v1/projects/{project['id']}/tasks/available",
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        # 所有任务应已回滚 — backlog 或 ready 中均无
        backlog_tasks = [t for t in data2.get("items", [])]
        assert len(backlog_tasks) == 0, (
            f"期望创建 0 个任务，实际创建了 {len(backlog_tasks)} 个"
        )

    async def test_create_batch_with_batch_id(
        self, client: AsyncClient, seed: SeedData,
    ):
        """批次中所有任务共享相同的 batch_id。"""
        project = await _create_project(client, seed)
        batch = await _create_batch(client, seed, project["id"])

        resp = await client.post(
            f"/v1/projects/{project['id']}/tasks/batch",
            json={
                "tasks": [
                    {
                        "title": "Batch Task 1",
                        "description": "Task in batch",
                        "batch_id": batch["id"],
                        "verifications": [{"type": "manual", "description": "Check batch task one works"}],
                    },
                    {
                        "title": "Batch Task 2",
                        "description": "Also in batch",
                        "batch_id": batch["id"],
                        "verifications": [{"type": "manual", "description": "Check batch task two works"}],
                    },
                ]
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 2
        assert data[0]["batch_id"] == batch["id"]
        assert data[1]["batch_id"] == batch["id"]


# ── 任务终止 ──────────────────────────────────────────────────────────


class TestTerminateTask:
    """任务终止端点（P8-B9，I2 基础形态）。"""

    async def test_terminate_from_in_progress(
        self, client: AsyncClient, seed: SeedData,
    ):
        """终止一个已 claim/assign 的任务 — 清除所有权。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # Assign 任务使其进入 IN_PROGRESS
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

        # 终止
        resp = await client.post(
            f"/v1/tasks/{task['id']}/terminate",
            json={"reason": "No longer needed", "expected_version": assigned["version_no"]},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["owner_type"] is None
        assert data["owner_id"] is None

    async def test_terminate_from_backlog(
        self, client: AsyncClient, seed: SeedData,
    ):
        """终止一个 backlog 任务（READY 也从 backlog 经状态机视为合法）。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # 先将任务转为 ready（backlog → ready）
        from src.db import async_session_factory
        from src.services.task_service import get_task, ready_task

        async with async_session_factory() as db:
            t = await get_task(db, task["id"])
            await ready_task(
                db, task["id"],
                expected_version=t.version_no,
                actor_type="human", actor_id=seed.member_id, team_id=seed.team_id,
            )
            await db.commit()

        # 重新读取以获取最新版本
        resp = await client.get(
            f"/v1/tasks/{task['id']}", headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        ready = resp.json()

        resp = await client.post(
            f"/v1/tasks/{task['id']}/terminate",
            json={"reason": "Obsolete", "expected_version": ready["version_no"]},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    async def test_terminate_completed_fails(
        self, client: AsyncClient, seed: SeedData,
    ):
        """终止已完成任务时返回 406 InvalidStateTransition。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # Assign、submit、通过验证完成
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
        from sqlalchemy import select

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
                "evidence": {"output_access": {"type": "inline", "value": "task completed"}},
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": assigned["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        submitted = resp.json()

        resp = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={
                "status": "passed",
                "expected_task_version": submitted["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        # 重新读取已完成任务的版本
        resp = await client.get(
            f"/v1/tasks/{task['id']}", headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        completed = resp.json()
        assert completed["status"] == "completed"

        # 终止应失败 — completed 没有出边
        resp = await client.post(
            f"/v1/tasks/{task['id']}/terminate",
            json={"reason": "Too late", "expected_version": completed["version_no"]},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 400

    async def test_terminate_version_conflict(
        self, client: AsyncClient, seed: SeedData,
    ):
        """过期版本号返回 409。"""
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

        # 使用过期版本号（任务刚被 assign，版本已递增）
        resp = await client.post(
            f"/v1/tasks/{task['id']}/terminate",
            json={"reason": "Stale", "expected_version": task["version_no"]},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 409


# ── 批次完成事件 ──────────────────────────────────────────────────────


class TestBatchCompletion:
    """批次完成事件发射（P8-B9）。"""

    async def test_batch_completed_event(
        self, client: AsyncClient, seed: SeedData,
    ):
        """批内所有任务到达终态时触发 batch.completed。"""
        project = await _create_project(client, seed)
        batch = await _create_batch(client, seed, project["id"])

        # 在同一批次中创建 2 个任务
        task1 = await _create_task(
            client, seed, project["id"], title="Batch Task 1", batch_id=batch["id"],
        )
        task2 = await _create_task(
            client, seed, project["id"], title="Batch Task 2", batch_id=batch["id"],
        )

        # 取消两个任务（终态）
        for t in [task1, task2]:
            resp = await client.post(
                f"/v1/tasks/{t['id']}/cancel?expected_version={t['version_no']}",
                headers=auth_header(seed.token),
            )
            assert resp.status_code == 200

        # 验证 batch.completed 事件存在
        events = await _get_events(client, seed)
        completed_events = [
            e for e in events
            if e["event_type"] == "batch.completed"
            and e["target_id"] == batch["id"]
        ]
        assert len(completed_events) == 1, (
            f"期望 1 个 batch.completed 事件，实际 {len(completed_events)} 个"
        )
        assert completed_events[0]["payload"]["batch_id"] == batch["id"]
        assert completed_events[0]["payload"]["completed_task_count"] == 2

    async def test_batch_not_completed_partial(
        self, client: AsyncClient, seed: SeedData,
    ):
        """部分任务仍活跃时不会触发 batch.completed。"""
        project = await _create_project(client, seed)
        batch = await _create_batch(client, seed, project["id"])

        task1 = await _create_task(
            client, seed, project["id"], title="Task 1", batch_id=batch["id"],
        )
        task2 = await _create_task(
            client, seed, project["id"], title="Task 2", batch_id=batch["id"],
        )

        # 只取消一个任务
        resp = await client.post(
            f"/v1/tasks/{task1['id']}/cancel?expected_version={task1['version_no']}",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        # batch.completed 必须不存在
        events = await _get_events(client, seed)
        completed_events = [
            e for e in events
            if e["event_type"] == "batch.completed" and e["target_id"] == batch["id"]
        ]
        assert len(completed_events) == 0, (
            "任务仍活跃时不应触发 batch.completed"
        )

    async def test_batch_completed_via_terminate(
        self, client: AsyncClient, seed: SeedData,
    ):
        """所有任务被终止（不只是取消）时触发 batch.completed。"""
        project = await _create_project(client, seed)
        batch = await _create_batch(client, seed, project["id"])

        task = await _create_task(
            client, seed, project["id"], title="Solo", batch_id=batch["id"],
        )

        # Assign 然后终止
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

        resp = await client.post(
            f"/v1/tasks/{task['id']}/terminate",
            json={"reason": "Done", "expected_version": assigned["version_no"]},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        # 验证 batch.completed 存在
        events = await _get_events(client, seed)
        completed_events = [
            e for e in events
            if e["event_type"] == "batch.completed" and e["target_id"] == batch["id"]
        ]
        assert len(completed_events) == 1, (
            "终止应为该唯一任务触发 batch.completed"
        )


# ── WS 信号验证 ───────────────────────────────────────────────────────


class TestWSSignals:
    """验证关键的 WS 信号事件已发射（Event→WS 桥接已建成）。"""

    async def test_task_submitted_signal(
        self, client: AsyncClient, seed: SeedData,
    ):
        """task.submitted 事件已记录（通过 WS 桥接自动广播）。"""
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
        from sqlalchemy import select

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
                "evidence": {"output_access": {"type": "inline", "value": "task completed"}},
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": assigned["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        submitted_events = [
            e for e in events
            if e["event_type"] == "task.submitted" and e["target_id"] == task["id"]
        ]
        assert len(submitted_events) == 1
        assert submitted_events[0]["payload"]["new_status"] == "in_verification"

    async def test_task_rejected_signal(
        self, client: AsyncClient, seed: SeedData,
    ):
        """验证失败时 task.rejected 事件通过 WS 广播。"""
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
        from sqlalchemy import select

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
                "evidence": {"output_access": {"type": "inline", "value": "task completed"}},
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": assigned["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        submitted = resp.json()

        resp = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={
                "status": "failed",
                "rejection_reason": "Not good",
                "expected_task_version": submitted["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        rejected_events = [
            e for e in events
            if e["event_type"] == "task.rejected" and e["target_id"] == task["id"]
        ]
        assert len(rejected_events) == 1
        assert rejected_events[0]["payload"]["new_status"] == "rejected"

    async def test_batch_completed_signal(
        self, client: AsyncClient, seed: SeedData,
    ):
        """batch.completed 事件通过 WS 广播（B9 新增 EventType）。"""
        project = await _create_project(client, seed)
        batch = await _create_batch(client, seed, project["id"])

        task = await _create_task(
            client, seed, project["id"], title="Batch Task", batch_id=batch["id"],
        )

        resp = await client.post(
            f"/v1/tasks/{task['id']}/cancel?expected_version={task['version_no']}",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        completed_events = [
            e for e in events
            if e["event_type"] == "batch.completed" and e["target_id"] == batch["id"]
        ]
        assert len(completed_events) == 1, (
            "batch.completed 事件应发射并通过 WS 广播"
        )
