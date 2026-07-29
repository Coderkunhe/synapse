"""P11-B87/B92 Orchestrator Status 端点测试 — Builder 心跳检测（PFL-070 + B92 双源增强）。"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient
from datetime import datetime, timedelta, timezone

from src.auth import hash_api_key, hash_project_key
from src.constants import WorkerActorType, WorkerStatus
from src.db import async_session_factory
from src.models.event import Event
from src.models.project import Project
from src.models.project_actor_role import ProjectActorRole
from src.models.worker import Worker
from src.utils.id_gen import generate_id

from tests.conftest import SeedData


# ═══════════════════════════════════════════════════════════════════
# P11-B87 Orchestrator Status (PFL-070)
# ═══════════════════════════════════════════════════════════════════


class TestOrchestratorStatus:
    """GET /projects/{pid}/orchestrator-status — Builder 心跳检测端点（PFL-070 · B87）。

    端点使用手动 token 提取认证（与 protocol 端点一致），
    支持 Worker API Key 和 project_key 两种 Bearer token。
    """

    async def _create_worker_with_key(self, db, *, team_id: str, name: str, heartbeat_offset_minutes: int = 0):
        """Helper: create a Worker with a known API key and return (worker_id, raw_key)."""
        raw_key = "sk-test-" + secrets.token_hex(16)
        key_hash = hash_api_key(raw_key)
        worker_id = generate_id("worker")

        heartbeat = datetime.now(timezone.utc)
        if heartbeat_offset_minutes > 0:
            heartbeat -= timedelta(minutes=heartbeat_offset_minutes)

        db.add(Worker(
            id=worker_id, name=name, team_id=team_id,
            actor_type=WorkerActorType.AGENT, status=WorkerStatus.ACTIVE,
            api_key_hash=key_hash,
            last_heartbeat_at=heartbeat,
        ))
        return worker_id, raw_key

    @pytest.mark.asyncio
    async def test_orchestrator_online(self, client: AsyncClient, seed: SeedData):
        """O 心跳新鲜 → online=true, heartbeat_age_seconds ≤ 120。"""
        project_id = generate_id("project")

        async with async_session_factory() as db:
            db.add(Project(id=project_id, team_id=seed.team_id, name="Test O Status", slug="test-o-status"))
            await db.flush()
            worker_id, raw_key = await self._create_worker_with_key(db, team_id=seed.team_id, name="Test O")
            db.add(ProjectActorRole(
                id=generate_id("project_actor_role"), project_id=project_id,
                worker_id=worker_id, role="orchestrator",
            ))
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{project_id}/orchestrator-status",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["online"] is True
        assert data["worker_id"] == worker_id
        assert data["heartbeat_age_seconds"] is not None
        assert data["heartbeat_age_seconds"] <= 120
        assert data["detection_source"] == "heartbeat"

    # ── B92: 双源容错 — event_activity fallback ──

    @pytest.mark.asyncio
    async def test_dual_source_event_activity_fallback(self, client: AsyncClient, seed: SeedData):
        """心跳过期但近期 Event 活动存在 → online=true, detection_source=event_activity。"""
        project_id = generate_id("project")

        async with async_session_factory() as db:
            db.add(Project(
                id=project_id, team_id=seed.team_id, name="Dual Source", slug="dual-source",
            ))
            await db.flush()
            # O with stale heartbeat (10 min ago)
            worker_id, raw_key = await self._create_worker_with_key(
                db, team_id=seed.team_id, name="O Stale HB", heartbeat_offset_minutes=10,
            )
            db.add(ProjectActorRole(
                id=generate_id("project_actor_role"), project_id=project_id,
                worker_id=worker_id, role="orchestrator",
            ))
            # Add a recent event from O (within 120s)
            db.add(Event(
                id=generate_id("event"),
                team_id=seed.team_id,
                event_type="task.created",
                actor_type="worker",
                actor_id=worker_id,
                target_type="task",
                target_id=generate_id("task"),
                payload='{"task_id": "tsk_test"}',
            ))
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{project_id}/orchestrator-status",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["online"] is True
        assert data["worker_id"] == worker_id
        assert data["detection_source"] == "event_activity"
        # heartbeat_age_seconds should still be the stale value
        assert data["heartbeat_age_seconds"] > 120

    @pytest.mark.asyncio
    async def test_dual_source_both_stale_no_events(self, client: AsyncClient, seed: SeedData):
        """心跳过期且无近期 Event → online=false, detection_source=None。"""
        project_id = generate_id("project")

        async with async_session_factory() as db:
            db.add(Project(
                id=project_id, team_id=seed.team_id, name="Both Stale", slug="both-stale",
            ))
            await db.flush()
            worker_id, raw_key = await self._create_worker_with_key(
                db, team_id=seed.team_id, name="O Stale No Events", heartbeat_offset_minutes=10,
            )
            db.add(ProjectActorRole(
                id=generate_id("project_actor_role"), project_id=project_id,
                worker_id=worker_id, role="orchestrator",
            ))
            # No recent events
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{project_id}/orchestrator-status",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["online"] is False
        assert data["worker_id"] == worker_id
        assert data["detection_source"] is None
        assert data["heartbeat_age_seconds"] > 120

    @pytest.mark.asyncio
    async def test_dual_source_event_activity_respects_timeout(self, client: AsyncClient, seed: SeedData):
        """Event 活动也在 timeout 外 → 双源皆过期，online=false。"""
        project_id = generate_id("project")

        async with async_session_factory() as db:
            db.add(Project(
                id=project_id, team_id=seed.team_id, name="Timeout", slug="timeout",
            ))
            await db.flush()
            worker_id, raw_key = await self._create_worker_with_key(
                db, team_id=seed.team_id, name="O Old Events", heartbeat_offset_minutes=10,
            )
            db.add(ProjectActorRole(
                id=generate_id("project_actor_role"), project_id=project_id,
                worker_id=worker_id, role="orchestrator",
            ))
            await db.flush()

            # Insert an old event (5 min ago — outside 120s timeout)
            old_event = Event(
                id=generate_id("event"),
                team_id=seed.team_id,
                event_type="task.created",
                actor_type="worker",
                actor_id=worker_id,
                target_type="task",
                target_id=generate_id("task"),
                payload='{"task_id": "tsk_old"}',
            )
            old_event.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            db.add(old_event)
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{project_id}/orchestrator-status",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["online"] is False
        assert data["detection_source"] is None

    @pytest.mark.asyncio
    async def test_orchestrator_offline_stale_heartbeat(self, client: AsyncClient, seed: SeedData):
        """O 心跳过期 >120s → online=false。"""
        project_id = generate_id("project")

        async with async_session_factory() as db:
            db.add(Project(id=project_id, team_id=seed.team_id, name="Test O Offline", slug="test-o-offline"))
            await db.flush()
            worker_id, raw_key = await self._create_worker_with_key(
                db, team_id=seed.team_id, name="Test O Stale", heartbeat_offset_minutes=10,
            )
            db.add(ProjectActorRole(
                id=generate_id("project_actor_role"), project_id=project_id,
                worker_id=worker_id, role="orchestrator",
            ))
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{project_id}/orchestrator-status",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["online"] is False
        assert data["worker_id"] == worker_id
        assert data["heartbeat_age_seconds"] > 120
        assert data["detection_source"] is None  # both heartbeat and events stale

    @pytest.mark.asyncio
    async def test_orchestrator_none_registered(self, client: AsyncClient, seed: SeedData):
        """项目无 O → online=false, worker_id=null, heartbeat_age_seconds=null。"""
        project_id = generate_id("project")
        raw_key = "sk-test-" + secrets.token_hex(16)

        async with async_session_factory() as db:
            db.add(Project(id=project_id, team_id=seed.team_id, name="No O", slug="no-o"))
            # Create a non-orchestrator worker to authenticate with
            db.add(Worker(
                id=generate_id("worker"), name="B Worker", team_id=seed.team_id,
                actor_type=WorkerActorType.AGENT, status=WorkerStatus.ACTIVE,
                api_key_hash=hash_api_key(raw_key),
            ))
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{project_id}/orchestrator-status",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["online"] is False
        assert data["worker_id"] is None
        assert data["heartbeat_age_seconds"] is None
        assert data["detection_source"] is None

    # ── B90: project_key 认证路径覆盖 ──

    @pytest.mark.asyncio
    async def test_orchestrator_status_via_project_key(self, client: AsyncClient, seed: SeedData):
        """project_key Bearer token 认证 → 同 Worker API key 路径结果一致（B90 补测）。"""
        project_id = generate_id("project")
        raw_project_key = "pk-test-" + secrets.token_hex(16)

        async with async_session_factory() as db:
            db.add(Project(
                id=project_id, team_id=seed.team_id, name="PK Auth", slug="pk-auth",
                project_key_hash=hash_project_key(raw_project_key),
            ))
            await db.flush()
            # Register an orchestrator with fresh heartbeat
            worker_id, _ = await self._create_worker_with_key(db, team_id=seed.team_id, name="PK O")
            db.add(ProjectActorRole(
                id=generate_id("project_actor_role"), project_id=project_id,
                worker_id=worker_id, role="orchestrator",
            ))
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{project_id}/orchestrator-status",
            headers={"Authorization": f"Bearer {raw_project_key}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["online"] is True
        assert data["worker_id"] == worker_id
        assert data["heartbeat_age_seconds"] <= 120
        assert data["detection_source"] == "heartbeat"