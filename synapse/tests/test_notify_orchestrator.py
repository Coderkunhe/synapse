"""Tests for P12-B46: Orchestrator notification endpoint."""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestNotifyOrchestrator:
    """POST /projects/{pid}/tasks/{tid}/notify — P12-B46 PFL-151 Option A."""

    @pytest.mark.asyncio
    async def test_notify_creates_message_and_returns_200(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Builder notifies O about a task — 200 with notified list."""
        headers = auth_header(seed.token)

        # ── Setup: project + task ──
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Notify Test", "slug": _uniq_slug("notify")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Task needing O attention",
                "description": "A task waiting for verification",
                "priority": "p2",
                "verifications": [
                    {"type": "manual", "description": "Verify output file exists at path", "criteria": {"path": "/tmp/out.txt"}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        # ── Notify ──
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks/{task_id}/notify",
            json={"reason": "awaiting_verification"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["task_id"] == task_id
        assert isinstance(data["notified_orchestrator_ids"], list)
        assert "Notified" in data["message"]

    @pytest.mark.asyncio
    async def test_notify_without_body_defaults_reason(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Notify without request body — still 200, uses default reason."""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Notify Default", "slug": _uniq_slug("ndef")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Default reason task",
                "description": "Testing default reason",
                "priority": "p3",
                "verifications": [
                    {"type": "manual", "description": "Verify output is correct format", "criteria": {"format": "json"}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        # ── Notify without body ──
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks/{task_id}/notify",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_notify_nonexistent_task_returns_404(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Notifying a non-existent task — 404."""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Notify 404", "slug": _uniq_slug("n404")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        resp = await client.post(
            f"/v1/projects/{project_id}/tasks/nonexistent_task/notify",
            json={"reason": "test"},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_notify_wrong_project_returns_404(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Notifying with correct task_id but wrong project_id — 404."""
        headers = auth_header(seed.token)

        # Create two projects
        proj1 = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Project A", "slug": _uniq_slug("prja")},
            headers=headers,
        )
        assert proj1.status_code == 201, proj1.text
        pid1 = proj1.json()["id"]

        proj2 = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Project B", "slug": _uniq_slug("prjb")},
            headers=headers,
        )
        assert proj2.status_code == 201, proj2.text
        pid2 = proj2.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{pid1}/tasks",
            json={
                "title": "Task in Project A",
                "description": "Belongs to project A",
                "priority": "p3",
                "verifications": [
                    {"type": "manual", "description": "Verify output is correct format", "criteria": {"format": "json"}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        # ── Notify using wrong project_id ──
        resp = await client.post(
            f"/v1/projects/{pid2}/tasks/{task_id}/notify",
            json={"reason": "test"},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_notify_requires_auth(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Notify without auth header — 401 or 403."""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Notify Auth", "slug": _uniq_slug("nauth")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Auth test task",
                "description": "Testing auth requirement",
                "priority": "p3",
                "verifications": [
                    {"type": "manual", "description": "Verify output is correct format", "criteria": {"format": "json"}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        # ── Notify without auth ──
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks/{task_id}/notify",
            json={"reason": "test"},
        )
        assert resp.status_code in (401, 403), resp.text
