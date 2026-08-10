"""Tests for P13-B9: O SLA auto-escalation detector (escalation_service.py).

P12-B47 原 5 tests → P13-B9 扩展为覆盖实际 escalation 触发路径。
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header
from tests.harness.time_travel import TimeTravel


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


# ── P12-B47 原有 tests (保留) ────────────────────────────────────────

class TestVerificationEscalation:
    """P13-B9: detect_stale_verifications_escalation() — 梯度响应 + 实际触发路径。"""

    @pytest.mark.asyncio
    async def test_no_escalation_for_fresh_verification(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Task just entered in_verification — should not be escalated."""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Esc Fresh", "slug": _uniq_slug("escf")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        pid = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{pid}/tasks",
            json={
                "title": "Fresh verification test",
                "description": "Testing that fresh verifications are not escalated",
                "priority": "p2",
                "verifications": [
                    {"type": "manual", "description": "Check output format is valid", "criteria": {"format": "json"}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text

        # The task is still in BACKLOG — it shouldn't be escalated
        from src.db import async_session_factory
        from src.services.escalation_service import detect_stale_verifications_escalation

        async with async_session_factory() as db:
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120,
            )
            assert result["escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_escalation_detector_runs_without_error(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Verify the escalation detector runs without errors on empty/mixed state."""
        from src.db import async_session_factory
        from src.services.escalation_service import detect_stale_verifications_escalation

        async with async_session_factory() as db:
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120,
            )
            assert result["escalated_count"] == 0
            assert isinstance(result["escalated_task_ids"], list)

    @pytest.mark.asyncio
    async def test_escalation_skips_tasks_past_revert_threshold(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Tasks past the revert threshold should NOT be escalated (handled by auto-revert)."""
        from src.db import async_session_factory
        from src.services.escalation_service import detect_stale_verifications_escalation

        async with async_session_factory() as db:
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=1, revert_minutes=2,
            )
            assert result["escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_escalation_called_from_reaper_import(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Verify the escalation function is properly importable and callable."""
        from src.services.escalation_service import detect_stale_verifications_escalation
        from src.db import async_session_factory

        async with async_session_factory() as db:
            result = await detect_stale_verifications_escalation(
                db,
                escalation_minutes=10,
                revert_minutes=120,
                cooldown_minutes=30,
            )
            assert "escalated_count" in result
            assert "escalated_task_ids" in result
            assert result["escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_config_values_accessible(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Verify the new config settings are accessible."""
        from src.config import settings

        assert hasattr(settings, "verification_escalation_minutes")
        assert hasattr(settings, "verification_escalation_cooldown_minutes")
        assert settings.verification_escalation_minutes == 10
        assert settings.verification_escalation_cooldown_minutes == 30


# ── P13-B9 新增: 实际 escalation 触发路径 ─────────────────────────────

class TestEscalationActualTrigger:
    """Tests that actually trigger the escalation path with stale IN_VERIFICATION tasks."""

    @pytest.mark.asyncio
    async def test_escalation_fires_for_stale_in_verification(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Task in IN_VERIFICATION past escalation threshold → escalation fires."""
        headers = auth_header(seed.token)

        # 1. Create project + task with verification
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Esc Trigger", "slug": _uniq_slug("esct")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        pid = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{pid}/tasks",
            json={
                "title": "Stale verification escalation test",
                "description": "This task will be aged past the escalation threshold",
                "priority": "p2",
                "verifications": [
                    {"type": "manual", "description": "Check output format is valid JSON", "criteria": {"format": "json"}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        tid = task_resp.json()["id"]

        # 2. Assign + start the task to get it into a workflow state
        # Directly manipulate the DB to put task in IN_VERIFICATION and age it
        from src.db import async_session_factory
        from src.constants import TaskStatus

        async with async_session_factory() as db:
            from src.models.task import Task
            task = await db.get(Task, tid)
            assert task is not None

            # Set status to IN_VERIFICATION
            task.status = TaskStatus.IN_VERIFICATION

            # Age updated_at past escalation threshold (10 min + buffer)
            tt = TimeTravel(db)
            await tt.advance_updated_at(tid, minutes=15)
            await db.commit()

        # 3. Run the escalation detector
        async with async_session_factory() as db:
            from src.services.escalation_service import detect_stale_verifications_escalation
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120,
            )
            await db.commit()

            assert result["escalated_count"] == 1
            assert tid in result["escalated_task_ids"]

        # 4. Verify the escalated event was recorded
        async with async_session_factory() as db:
            from src.models.event import Event
            from sqlalchemy import select
            stmt = select(Event).where(
                Event.target_id == tid,
                Event.event_type == "task.escalated",
            )
            events_result = await db.execute(stmt)
            events = events_result.scalars().all()
            assert len(events) == 1
            import json as _json
            payload = _json.loads(events[0].payload) if isinstance(events[0].payload, str) else events[0].payload
            assert payload["reason"] == "orchestrator_sla_timeout"

    @pytest.mark.asyncio
    async def test_escalation_cooldown_prevents_duplicates(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Cooldown window prevents escalating the same task twice."""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Esc Cooldown", "slug": _uniq_slug("esco")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        pid = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{pid}/tasks",
            json={
                "title": "Cooldown test task",
                "description": "Testing cooldown prevents duplicate escalation",
                "priority": "p2",
                "verifications": [
                    {"type": "manual", "description": "Check cooldown prevents duplicates", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        tid = task_resp.json()["id"]

        from src.db import async_session_factory
        from src.constants import TaskStatus

        # Setup: put task in IN_VERIFICATION and age it
        async with async_session_factory() as db:
            from src.models.task import Task
            task = await db.get(Task, tid)
            task.status = TaskStatus.IN_VERIFICATION
            tt = TimeTravel(db)
            await tt.advance_updated_at(tid, minutes=15)
            await db.commit()

        # First run: escalation should fire
        async with async_session_factory() as db:
            from src.services.escalation_service import detect_stale_verifications_escalation
            result1 = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120, cooldown_minutes=30,
            )
            await db.commit()
            assert result1["escalated_count"] == 1

        # Second run immediately: cooldown should prevent duplicate
        async with async_session_factory() as db:
            result2 = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120, cooldown_minutes=30,
            )
            await db.commit()
            assert result2["escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_escalation_respects_revert_boundary(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Tasks aged past revert threshold → NOT escalated (left for auto-revert)."""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Esc Revert", "slug": _uniq_slug("esrv")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        pid = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{pid}/tasks",
            json={
                "title": "Past revert boundary task",
                "description": "Should NOT be escalated — past revert threshold",
                "priority": "p2",
                "verifications": [
                    {"type": "manual", "description": "Check task past revert boundary", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        tid = task_resp.json()["id"]

        from src.db import async_session_factory
        from src.constants import TaskStatus

        # Setup: put task in IN_VERIFICATION and age it PAST the revert threshold
        async with async_session_factory() as db:
            from src.models.task import Task
            task = await db.get(Task, tid)
            task.status = TaskStatus.IN_VERIFICATION
            tt = TimeTravel(db)
            await tt.advance_updated_at(tid, minutes=150)  # Past 120 min revert
            await db.commit()

        async with async_session_factory() as db:
            from src.services.escalation_service import detect_stale_verifications_escalation
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120,
            )
            await db.commit()
            assert result["escalated_count"] == 0  # Too old for escalation

    @pytest.mark.asyncio
    async def test_escalation_service_import_path(
        self, client: AsyncClient, seed: SeedData,
    ):
        """P13-B9: escalation_service.py is the canonical import path."""
        from src.services.escalation_service import detect_stale_verifications_escalation
        from src.db import async_session_factory

        async with async_session_factory() as db:
            result = await detect_stale_verifications_escalation(db)
            assert result["escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_backward_compat_import_from_stale_task_detector(
        self, client: AsyncClient, seed: SeedData,
    ):
        """P13-B9: stale_task_detector still re-exports for backward compat."""
        from src.services.stale_task_detector import detect_stale_verifications_escalation
        from src.db import async_session_factory

        async with async_session_factory() as db:
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120,
            )
            assert result["escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_skip_escalation_metadata_prevents_cascade(
        self, client: AsyncClient, seed: SeedData,
    ):
        """P14-B8: Tasks with skip_escalation metadata are NOT escalated — blocks G2 cascade."""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Skip Esc", "slug": _uniq_slug("skes")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        pid = proj_resp.json()["id"]

        # Create a task WITH skip_escalation metadata (simulating G2 auto-created test task)
        task_resp = await client.post(
            f"/v1/projects/{pid}/tasks",
            json={
                "title": "Skip escalation test task",
                "description": "This task has skip_escalation metadata — should NOT be escalated",
                "priority": "p2",
                "metadata": {"skip_escalation": True},
                "verifications": [
                    {"type": "manual", "description": "Should not trigger escalation", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        tid = task_resp.json()["id"]

        from src.db import async_session_factory
        from src.constants import TaskStatus

        # Setup: put task in IN_VERIFICATION and age it past escalation threshold
        async with async_session_factory() as db:
            from src.models.task import Task
            task = await db.get(Task, tid)
            task.status = TaskStatus.IN_VERIFICATION
            tt = TimeTravel(db)
            await tt.advance_updated_at(tid, minutes=15)
            await db.commit()

        # Run escalation detector — should skip this task
        async with async_session_factory() as db:
            from src.services.escalation_service import detect_stale_verifications_escalation
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120,
            )
            await db.commit()
            assert result["escalated_count"] == 0, (
                f"Task with skip_escalation metadata should NOT be escalated, "
                f"but got: {result}"
            )

        # Verify NO escalated event was recorded
        async with async_session_factory() as db:
            from src.models.event import Event
            from sqlalchemy import select
            stmt = select(Event).where(
                Event.target_id == tid,
                Event.event_type == "task.escalated",
            )
            events_result = await db.execute(stmt)
            events = events_result.scalars().all()
            assert len(events) == 0, (
                f"Expected 0 escalated events for skip_escalation task, got {len(events)}"
            )
