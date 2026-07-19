"""P10-B26: Workflow + WorkflowRole API 端点测试 — HTTP E2E."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


async def _ensure_test_project(seed: SeedData) -> str:
    """Create a test project and return its ID."""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.models.project import Project
    from src.constants import ProjectStatus

    project_id = generate_id("project")
    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="WF Test Project",
            slug=f"wf-test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.commit()
    return project_id


async def _ensure_test_worker(seed: SeedData, name: str = "Target Worker") -> str:
    """Create a test human worker and return its ID."""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.models.worker import Worker
    from src.constants import WorkerActorType, WorkerStatus

    worker_id = generate_id("worker")
    async with async_session_factory() as db:
        worker = Worker(
            id=worker_id,
            name=name,
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add(worker)
        await db.commit()
    return worker_id


async def _create_workflow(client: AsyncClient, seed: SeedData, project_id: str, name: str = "Test Workflow") -> dict:
    """Create a Workflow via API and return response json."""
    resp = await client.post(
        f"/v1/admin/projects/{project_id}/workflows",
        json={"name": name, "description": "A test workflow"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    return resp.json()


# ═══════════════════════════════════════════════════════════════
# Workflow CRUD Endpoints
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_workflow_endpoint(client: AsyncClient, seed: SeedData):
    """POST /admin/projects/{pid}/workflows — create a Workflow."""
    project_id = await _ensure_test_project(seed)

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/workflows",
        json={"name": "P10 Architecture", "description": "Upgrade auth"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "P10 Architecture"
    assert data["description"] == "Upgrade auth"
    assert data["status"] == "active"
    assert data["project_id"] == project_id
    assert data["id"].startswith("wfl_")


@pytest.mark.asyncio
async def test_create_workflow_defaults_status(client: AsyncClient, seed: SeedData):
    """POST /admin/projects/{pid}/workflows — defaults status to active."""
    project_id = await _ensure_test_project(seed)

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/workflows",
        json={"name": "Minimal WF"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_list_workflows_endpoint(client: AsyncClient, seed: SeedData):
    """GET /admin/projects/{pid}/workflows — list Workflows."""
    project_id = await _ensure_test_project(seed)

    # Create two workflows
    await _create_workflow(client, seed, project_id, "WF A")
    await _create_workflow(client, seed, project_id, "WF B")

    resp = await client.get(
        f"/v1/admin/projects/{project_id}/workflows",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == project_id
    assert len(data["workflows"]) == 2


@pytest.mark.asyncio
async def test_list_workflows_empty_project(client: AsyncClient, seed: SeedData):
    """GET /admin/projects/{pid}/workflows — empty project returns empty list."""
    project_id = await _ensure_test_project(seed)

    resp = await client.get(
        f"/v1/admin/projects/{project_id}/workflows",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    assert resp.json()["workflows"] == []


@pytest.mark.asyncio
async def test_get_workflow_endpoint(client: AsyncClient, seed: SeedData):
    """GET /admin/projects/{pid}/workflows/{wid} — get single Workflow."""
    project_id = await _ensure_test_project(seed)
    wf = await _create_workflow(client, seed, project_id, "Get Me")

    resp = await client.get(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == wf["id"]
    assert resp.json()["name"] == "Get Me"


@pytest.mark.asyncio
async def test_get_workflow_not_found(client: AsyncClient, seed: SeedData):
    """GET /admin/projects/{pid}/workflows/{wid} — 404 for unknown workflow."""
    project_id = await _ensure_test_project(seed)

    resp = await client.get(
        f"/v1/admin/projects/{project_id}/workflows/wfl_nonexistent",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_workflow_endpoint(client: AsyncClient, seed: SeedData):
    """PATCH /admin/projects/{pid}/workflows/{wid} — partial update."""
    project_id = await _ensure_test_project(seed)
    wf = await _create_workflow(client, seed, project_id, "Original")

    resp = await client.patch(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}",
        json={"name": "Updated", "description": "New desc"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated"
    assert data["description"] == "New desc"
    assert data["status"] == "active"  # unchanged


@pytest.mark.asyncio
async def test_complete_workflow_endpoint(client: AsyncClient, seed: SeedData):
    """POST /admin/projects/{pid}/workflows/{wid}/complete — mark completed."""
    project_id = await _ensure_test_project(seed)
    wf = await _create_workflow(client, seed, project_id, "Almost Done")

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/complete",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # Verify GET reflects the change
    resp2 = await client.get(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}",
        headers=auth_header(seed.token),
    )
    assert resp2.json()["status"] == "completed"


# ═══════════════════════════════════════════════════════════════
# WorkflowRole Endpoints
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_assign_workflow_role_endpoint(client: AsyncClient, seed: SeedData):
    """POST /admin/projects/{pid}/workflows/{wid}/roles — assign role."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)
    wf = await _create_workflow(client, seed, project_id)

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        json={"worker_id": worker_id, "role": "builder"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["worker_id"] == worker_id
    assert data["role"] == "builder"
    assert data["worker_name"] == "Target Worker"


@pytest.mark.asyncio
async def test_assign_workflow_role_upserts(client: AsyncClient, seed: SeedData):
    """POST .../roles — second call updates the role (upsert)."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)
    wf = await _create_workflow(client, seed, project_id)

    await client.post(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        json={"worker_id": worker_id, "role": "builder"},
        headers=auth_header(seed.token),
    )

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        json={"worker_id": worker_id, "role": "orchestrator"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "orchestrator"


@pytest.mark.asyncio
async def test_list_workflow_roles_endpoint(client: AsyncClient, seed: SeedData):
    """GET .../roles — list all role assignments."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)
    wf = await _create_workflow(client, seed, project_id)

    await client.post(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        json={"worker_id": worker_id, "role": "orchestrator"},
        headers=auth_header(seed.token),
    )

    resp = await client.get(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_id"] == wf["id"]
    assert len(data["roles"]) == 1
    assert data["roles"][0]["worker_id"] == worker_id
    assert data["roles"][0]["role"] == "orchestrator"


@pytest.mark.asyncio
async def test_list_workflow_roles_empty(client: AsyncClient, seed: SeedData):
    """GET .../roles — empty workflow returns empty list."""
    project_id = await _ensure_test_project(seed)
    wf = await _create_workflow(client, seed, project_id)

    resp = await client.get(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    assert resp.json()["roles"] == []


@pytest.mark.asyncio
async def test_revoke_workflow_role_endpoint(client: AsyncClient, seed: SeedData):
    """DELETE .../roles/{worker_id} — revoke a role."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)
    wf = await _create_workflow(client, seed, project_id)

    await client.post(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        json={"worker_id": worker_id, "role": "builder"},
        headers=auth_header(seed.token),
    )

    resp = await client.delete(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles/{worker_id}",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 204

    # Verify the list is now empty
    resp2 = await client.get(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles",
        headers=auth_header(seed.token),
    )
    assert resp2.json()["roles"] == []


@pytest.mark.asyncio
async def test_revoke_workflow_role_not_found(client: AsyncClient, seed: SeedData):
    """DELETE .../roles/{worker_id} — no-op for non-existent role."""
    project_id = await _ensure_test_project(seed)
    wf = await _create_workflow(client, seed, project_id)

    resp = await client.delete(
        f"/v1/admin/projects/{project_id}/workflows/{wf['id']}/roles/wrk_nonexistent",
        headers=auth_header(seed.token),
    )
    # 204 even if nothing to delete (consistent with admin.py project role revoke)
    assert resp.status_code == 204


# ═══════════════════════════════════════════════════════════════
# Permission Tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_workflow_endpoint_requires_auth(client: AsyncClient):
    """Workflow endpoints return 401 without authentication."""
    resp = await client.get(
        "/v1/admin/projects/proj_test/workflows",
    )
    assert resp.status_code == 401  # no auth → 401 (no JWT to validate)


@pytest.mark.asyncio
async def test_workflow_endpoint_not_found_project(client: AsyncClient, seed: SeedData):
    """Workflow endpoints return 404 for non-existent project."""
    resp = await client.get(
        "/v1/admin/projects/proj_nonexistent/workflows",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 404
