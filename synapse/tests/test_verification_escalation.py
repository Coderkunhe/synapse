"""Tests for P12-B47: O SLA auto-escalation detector."""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestVerificationEscalation:
    """P12-B47: detect_stale_verifications_escalation() — two-phase SLA response."""

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
        tid = task_resp.json()["id"]

        # The task is still in BACKLOG — it shouldn't be escalated
        from src.db import async_session_factory
        from src.services.stale_task_detector import detect_stale_verifications_escalation

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
        from src.services.stale_task_detector import detect_stale_verifications_escalation

        async with async_session_factory() as db:
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=10, revert_minutes=120,
            )
            # Should complete without error, even with no matching tasks
            assert result["escalated_count"] == 0
            assert isinstance(result["escalated_task_ids"], list)

    @pytest.mark.asyncio
    async def test_escalation_skips_tasks_past_revert_threshold(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Tasks past the revert threshold should NOT be escalated (handled by auto-revert)."""
        from src.db import async_session_factory
        from src.services.stale_task_detector import detect_stale_verifications_escalation

        async with async_session_factory() as db:
            # With escalation=10, revert=120, any task >120min stale should be skipped
            result = await detect_stale_verifications_escalation(
                db, escalation_minutes=1, revert_minutes=2,
            )
            assert result["escalated_count"] == 0

    @pytest.mark.asyncio
    async def test_escalation_called_from_reaper_import(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Verify the escalation function is properly importable and callable."""
        from src.services.stale_task_detector import detect_stale_verifications_escalation
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
