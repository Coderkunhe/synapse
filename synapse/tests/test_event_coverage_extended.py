"""P8-B8：事件覆盖测试（扩展）— Verification、Failure、Worker Scheduler、SM 一致性。

覆盖 P8-B8 补齐的三类缺口：verification 事件、failure/escalation 事件、
worker_scheduler 驱动的 agent runtime 事件、状态机一致性修复。
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



# ── Verification 事件测试 ───────────────────────────────────────────────


class TestVerificationEventCoverage:
    """验证 Verification 生命周期事件均正确写入。"""

    async def test_verification_executed_event(self, client: AsyncClient, seed: SeedData):
        """verification.executed 在每次验证检查时写入。"""
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
        ver_events = [e for e in events
                      if e["event_type"] == "verification.executed"
                      and e["target_id"] == ver_id]
        assert len(ver_events) == 1
        assert ver_events[0]["payload"]["verification_status"] == "passed"

    async def test_verification_reset_event(self, client: AsyncClient, seed: SeedData):
        """verification.reset 在拒绝后重新提交时写入。"""
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

        # 提交
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

        # 拒绝
        resp = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={
                "status": "failed",
                "rejection_reason": "Bad",
                "expected_task_version": submitted["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        # 重新读取获取更新后的版本
        resp = await client.get(
            f"/v1/tasks/{task['id']}", headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        rejected = resp.json()

        # REJECTED → IN_PROGRESS 转换（worker 在返工后重新接入）
        from src.db import async_session_factory as dbf2
        from src.task_state_machine import apply_transition

        async with dbf2() as db:
            from src.services.task_service import get_task as svc_get_task2
            t = await svc_get_task2(db, task["id"])
            event_type, payload = apply_transition(
                t, "in_progress",
                actor_type="human", actor_id=seed.member_id,
                context={"rework": True, "redo_count": t.redo_count},
            )
            from src.services.event_store import event_store as es
            await es.record(
                db,
                event_type=event_type,
                team_id=seed.team_id,
                actor_type="human",
                actor_id=seed.member_id,
                target_type="task",
                target_id=task["id"],
                payload=payload,
            )
            await db.commit()

        # 返工转换后重新读取更新后的版本
        resp = await client.get(
            f"/v1/tasks/{task['id']}", headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        in_progress_again = resp.json()

        # 重新提交（触发 verification.reset 事件）
        resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Fixed",
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": in_progress_again["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        reset_events = [e for e in events
                        if e["event_type"] == "verification.reset"
                        and e["target_id"] == ver_id]
        assert len(reset_events) == 1
        assert reset_events[0]["payload"]["previous_status"] == "failed"
        assert reset_events[0]["payload"]["new_status"] == "pending"
        assert reset_events[0]["payload"]["reason"] == "task_resubmitted"


# ── Failure 事件测试 ────────────────────────────────────────────────────


class TestFailureEventCoverage:
    """验证 failure/blocker/escalation 事件均正确写入。"""

    async def test_blocker_reported_event(self, client: AsyncClient, seed: SeedData):
        """task.blocker_reported 在 agent 报告阻塞时写入。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # 注册并握手 agent
        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        # B56: claim + report_blocker requires builder project role
        await ensure_project_role(
            client, project["id"], agent_data["id"], "builder", auth_header(seed.token),
        )

        # READY 然后 claim
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

        resp = await client.post(
            f"/v1/tasks/{task['id']}/claim?expected_version={ready_task_data['version_no']}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        claimed = resp.json()

        # Worker 报告阻塞
        resp = await client.post(
            f"/v1/tasks/{task['id']}/blocker",
            json={
                "blocker_type": "external_dependency",
                "description": "Need library X",
                "expected_version": claimed["version_no"],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        blocker_events = [e for e in events
                          if e["event_type"] == "task.blocker_reported"
                          and e["target_id"] == task["id"]]
        assert len(blocker_events) == 1
        assert blocker_events[0]["payload"]["blocker_type"] == "external_dependency"
        assert blocker_events[0]["payload"]["new_status"] == "ready"

    async def test_escalated_event(self, client: AsyncClient, seed: SeedData):
        """task.escalated 在 failure_count 达到 N_RETRY 时写入。"""
        from src.db import async_session_factory
        from src.services.failure_detector import _release_worker_tasks

        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # 注册、握手、READY、claim
        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        # B56: claim requires builder project role
        await ensure_project_role(
            client, project["id"], agent_data["id"], "builder", auth_header(seed.token),
        )

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

        resp = await client.post(
            f"/v1/tasks/{task['id']}/claim?expected_version={ready_task_data['version_no']}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        # 人为将 failure_count 设为 2（下一次失败触发升级）
        async with async_session_factory() as db:
            from src.models.task import Task
            t = await db.get(Task, task["id"])
            t.failure_count = 2
            await db.commit()

        # 触发释放（failure_count 2 → 3 → escalation）
        async with async_session_factory() as db:
            from src.models.worker import Worker
            agent = await db.get(Worker, agent_data["id"])
            await _release_worker_tasks(db, agent, reason="test_escalation")
            await db.commit()

        events = await _get_events(client, seed)
        escalated = [e for e in events
                     if e["event_type"] == "task.escalated"
                     and e["target_id"] == task["id"]]
        assert len(escalated) == 1
        assert escalated[0]["payload"]["failure_count"] == 3


# ── Worker scheduler 事件测试（P8-B8 缺口）──────────────────────────────


class TestWorkerSchedulerEvents:
    """验证 worker_scheduler 驱动的 agent runtime 事件（P8-B8 修复）。"""

    async def test_start_task_writes_runtime_busy_event(
        self, client: AsyncClient, seed: SeedData,
    ):
        """start_task() 通过状态机写入 agent.runtime.busy（P8-B8 修复）。"""
        from src.db import async_session_factory
        from src.services.worker_scheduler import start_task

        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # B56: claim requires builder project role
        await ensure_project_role(
            client, project["id"], agent_data["id"], "builder", auth_header(seed.token),
        )

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

        resp = await client.post(
            f"/v1/tasks/{task['id']}/claim?expected_version={ready_task_data['version_no']}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        # 直接调用 start_task（模拟 worker 开始工作）
        async with async_session_factory() as db:
            await start_task(db, agent_data["id"], task["id"])
            await db.commit()

        events = await _get_events(client, seed)
        busy_events = [
            e for e in events
            if e["event_type"] == "worker.runtime.busy"
            and e["target_id"] == agent_data["id"]
            and e["actor_type"] == "worker"
        ]
        assert len(busy_events) >= 1, "start_task should write agent.runtime.busy event"

    async def test_finish_current_task_writes_runtime_idle_event(
        self, client: AsyncClient, seed: SeedData,
    ):
        """finish_current_task() 通过状态机写入 agent.runtime.idle（P8-B8 修复）。"""
        from src.db import async_session_factory
        from src.services.worker_scheduler import finish_current_task, start_task

        agent_data, api_key = await _register_worker(client, seed)
        await _worker_handshake(client, agent_data["id"], api_key)

        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # B56: claim requires builder project role
        await ensure_project_role(
            client, project["id"], agent_data["id"], "builder", auth_header(seed.token),
        )

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

        resp = await client.post(
            f"/v1/tasks/{task['id']}/claim?expected_version={ready_task_data['version_no']}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        # 开始然后结束
        async with async_session_factory() as db:
            await start_task(db, agent_data["id"], task["id"])
            await db.commit()

        async with async_session_factory() as db:
            await finish_current_task(db, agent_data["id"])
            await db.commit()

        events = await _get_events(client, seed)
        idle_events = [
            e for e in events
            if e["event_type"] == "worker.runtime.idle"
            and e["target_id"] == agent_data["id"]
            and e["actor_type"] == "system"
        ]
        assert len(idle_events) >= 1, "finish_current_task should write agent.runtime.idle event"


# ── SM 一致性测试 ───────────────────────────────────────────────────────


class TestStateMachineConsistency:
    """验证状态机驱动的转换（P8-B8 一致性修复）。"""

    async def test_assign_from_ready_uses_task_claimed(
        self, client: AsyncClient, seed: SeedData,
    ):
        """assign_task 从 READY → IN_PROGRESS 发出 task.claimed（通过 SM）。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # 将任务设为 READY（BACKLOG → READY）
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
        ready = resp.json()

        # 从 READY → IN_PROGRESS 分配（SM 应发出 task.claimed 而非 task.assigned）
        resp = await client.post(
            f"/v1/tasks/{task['id']}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": ready["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        claimed = [e for e in events
                   if e["event_type"] == "task.claimed"
                   and e["target_id"] == task["id"]]
        assert len(claimed) == 1, (
            "READY→IN_PROGRESS should emit task.claimed (via SM), not task.assigned"
        )

    async def test_cancel_task_uses_state_machine(
        self, client: AsyncClient, seed: SeedData,
    ):
        """cancel_task 通过状态机写入 task.cancelled（原为直接赋值）。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        resp = await client.post(
            f"/v1/tasks/{task['id']}/cancel?expected_version={task['version_no']}",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        events = await _get_events(client, seed)
        cancelled = [e for e in events
                     if e["event_type"] == "task.cancelled"
                     and e["target_id"] == task["id"]]
        assert len(cancelled) == 1
        assert "previous_status" in cancelled[0]["payload"]
        assert "new_status" in cancelled[0]["payload"]
        assert cancelled[0]["payload"]["new_status"] == "cancelled"
