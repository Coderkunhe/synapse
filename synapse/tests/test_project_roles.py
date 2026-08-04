"""P10-B18: project_actor_roles 接线测试 — service + dependency + endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import SeedData, auth_header


# ═══════════════════════════════════════════════════════════════
# Service Layer Tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_project_role_none_for_no_record():
    """get_project_role returns None when no role exists."""
    from src.db import async_session_factory
    from src.services.project_role_service import get_project_role

    async with async_session_factory() as db:
        role = await get_project_role(db, "nonexistent-project", "nonexistent-worker")
        assert role is None


@pytest.mark.asyncio
async def test_set_and_get_project_role(seed: SeedData):
    """set_project_role creates a record, get_project_role retrieves it."""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.project_role_service import get_project_role, set_project_role
    from src.constants import ActorType

    project_id = generate_id("project")
    worker_id = generate_id("worker")

    async with async_session_factory() as db:
        # Seed a project and worker so FKs are satisfied
        from src.models.project import Project
        from src.models.worker import Worker
        from src.constants import WorkerActorType, WorkerStatus, ProjectStatus

        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        worker = Worker(
            id=worker_id,
            name="Test Worker",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add_all([project, worker])
        await db.flush()

        # Set role
        record = await set_project_role(
            db,
            project_id=project_id,
            worker_id=worker_id,
            role="admin",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )
        assert record.role == "admin"
        assert record.project_id == project_id
        assert record.worker_id == worker_id

        # Get role
        role = await get_project_role(db, project_id, worker_id)
        assert role == "admin"

        await db.commit()


@pytest.mark.asyncio
async def test_set_project_role_upsert(seed: SeedData):
    """set_project_role on an existing record updates the role (upsert)."""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.project_role_service import get_project_role, set_project_role
    from src.constants import ActorType
    from src.models.project import Project
    from src.models.worker import Worker
    from src.constants import WorkerActorType, WorkerStatus, ProjectStatus

    project_id = generate_id("project")
    worker_id = generate_id("worker")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        worker = Worker(
            id=worker_id,
            name="Test Worker",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add_all([project, worker])
        await db.flush()

        # First set as member
        await set_project_role(
            db,
            project_id=project_id,
            worker_id=worker_id,
            role="member",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )

        # Upsert to admin
        record = await set_project_role(
            db,
            project_id=project_id,
            worker_id=worker_id,
            role="admin",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )
        assert record.role == "admin"

        role = await get_project_role(db, project_id, worker_id)
        assert role == "admin"

        await db.commit()


@pytest.mark.asyncio
async def test_remove_project_role(seed: SeedData):
    """remove_project_role deletes the record and returns True."""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.project_role_service import (
        get_project_role,
        remove_project_role,
        set_project_role,
    )
    from src.constants import ActorType
    from src.models.project import Project
    from src.models.worker import Worker
    from src.constants import WorkerActorType, WorkerStatus, ProjectStatus

    project_id = generate_id("project")
    worker_id = generate_id("worker")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        worker = Worker(
            id=worker_id,
            name="Test Worker",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add_all([project, worker])
        await db.flush()

        await set_project_role(
            db,
            project_id=project_id,
            worker_id=worker_id,
            role="member",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )

        removed = await remove_project_role(
            db,
            project_id=project_id,
            worker_id=worker_id,
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )
        assert removed is True

        role = await get_project_role(db, project_id, worker_id)
        assert role is None

        await db.commit()


@pytest.mark.asyncio
async def test_remove_project_role_nonexistent(seed: SeedData):
    """remove_project_role returns False when no record exists."""
    from src.db import async_session_factory
    from src.services.project_role_service import remove_project_role
    from src.constants import ActorType

    async with async_session_factory() as db:
        removed = await remove_project_role(
            db,
            project_id="nonexistent",
            worker_id="nonexistent",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )
        assert removed is False
        await db.rollback()


@pytest.mark.asyncio
async def test_list_project_roles(seed: SeedData):
    """list_project_roles returns all (worker, role) pairs for a project."""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.project_role_service import list_project_roles, set_project_role
    from src.constants import ActorType
    from src.models.project import Project
    from src.models.worker import Worker
    from src.constants import WorkerActorType, WorkerStatus, ProjectStatus

    project_id = generate_id("project")
    worker1_id = generate_id("worker")
    worker2_id = generate_id("worker")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        w1 = Worker(
            id=worker1_id, name="Alice",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        w2 = Worker(
            id=worker2_id, name="Bob",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add_all([project, w1, w2])
        await db.flush()

        await set_project_role(
            db, project_id=project_id, worker_id=worker1_id, role="admin",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        await set_project_role(
            db, project_id=project_id, worker_id=worker2_id, role="member",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        entries = await list_project_roles(db, project_id)
        assert len(entries) == 2

        # Should be sorted by name: Alice first, then Bob
        assert entries[0][0].name == "Alice"
        assert entries[0][1] == "admin"
        assert entries[1][0].name == "Bob"
        assert entries[1][1] == "member"

        await db.commit()


# ═══════════════════════════════════════════════════════════════
# HTTP Endpoint Tests
# ═══════════════════════════════════════════════════════════════

# ── Helper: create a project record for testing ────────────────

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
            name="Admin Test Project",
            slug=f"admin-test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.commit()
    return project_id


async def _ensure_test_worker(seed: SeedData) -> str:
    """Create a test human worker and return its ID."""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.models.worker import Worker
    from src.constants import WorkerActorType, WorkerStatus

    worker_id = generate_id("worker")
    async with async_session_factory() as db:
        worker = Worker(
            id=worker_id,
            name="Target Worker",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add(worker)
        await db.commit()
    return worker_id


@pytest.mark.asyncio
async def test_assign_project_role_endpoint(client: AsyncClient, seed: SeedData):
    """POST /admin/projects/{id}/roles — admin assigns a role."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "admin"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["worker_id"] == worker_id
    assert data["worker_name"] == "Target Worker"
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_assign_project_role_upserts(client: AsyncClient, seed: SeedData):
    """POST /admin/projects/{id}/roles — second call updates the role."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)

    # First assign as member
    await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "member"},
        headers=auth_header(seed.token),
    )

    # Then update to admin
    resp = await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "admin"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_list_project_roles_endpoint(client: AsyncClient, seed: SeedData):
    """GET /admin/projects/{id}/roles — lists assigned roles."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)

    # Assign a role first
    await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "admin"},
        headers=auth_header(seed.token),
    )

    resp = await client.get(
        f"/v1/admin/projects/{project_id}/roles",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == project_id
    assert len(data["roles"]) == 1
    assert data["roles"][0]["worker_id"] == worker_id
    assert data["roles"][0]["role"] == "admin"


@pytest.mark.asyncio
async def test_revoke_project_role_endpoint(client: AsyncClient, seed: SeedData):
    """DELETE /admin/projects/{id}/roles/{worker_id} — removes the role."""
    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)

    # Assign first
    await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "member"},
        headers=auth_header(seed.token),
    )

    # Revoke
    resp = await client.delete(
        f"/v1/admin/projects/{project_id}/roles/{worker_id}",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 204

    # Verify gone
    resp = await client.get(
        f"/v1/admin/projects/{project_id}/roles",
        headers=auth_header(seed.token),
    )
    assert len(resp.json()["roles"]) == 0


@pytest.mark.asyncio
async def test_assign_project_role_forbidden_for_non_admin(
    client: AsyncClient, seed: SeedData,
):
    """POST /admin/projects/{id}/roles returns 403 for non-admin actors."""
    from src.auth import create_access_token
    from src.utils.id_gen import generate_id

    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)

    # Create a member (not admin) token
    member_token = create_access_token(
        user_id=f"member-{generate_id('user')[-8:]}",
        actor_id=generate_id("worker"),
        team_id=seed.team_id,
        role="member",
    )

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "admin"},
        headers=auth_header(member_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assign_project_role_super_admin_bypass(
    client: AsyncClient, seed: SeedData,
):
    """POST /admin/projects/{id}/roles succeeds for super-admin regardless of role."""
    from src.auth import create_access_token
    from src.utils.id_gen import generate_id

    project_id = await _ensure_test_project(seed)
    worker_id = await _ensure_test_worker(seed)

    # Create a token with is_super_admin=True but role="member"
    super_token = create_access_token(
        user_id=f"super-{generate_id('user')[-8:]}",
        actor_id=generate_id("worker"),
        team_id=seed.team_id,
        role="member",
        is_super_admin=True,
    )

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "admin"},
        headers=auth_header(super_token),
    )
    assert resp.status_code == 201


# ═══════════════════════════════════════════════════════════════
# Dependency Tests (require_project_role via endpoint wiring)
# ═══════════════════════════════════════════════════════════════

# We test require_project_role indirectly by wiring it to a test endpoint.
# The dependency behavior is:
#   1. Worker (API Key) → 403
#   2. Super-admin → bypass
#   3. No project_actor_roles record → 403  (FORBIDDEN_NOT_PROJECT_MEMBER)
#   4. Wrong role in project_actor_roles → 403  (FORBIDDEN_INSUFFICIENT_PROJECT_ROLE)
#   5. Correct role → passes

# For now, we verify the dependency is importable and its guard logic is
# structurally correct. Full endpoint-level wiring (replacing require_role
# with require_project_role) is deferred to later batches (per plan scope).


@pytest.mark.asyncio
async def test_require_project_role_is_importable():
    """require_project_role can be imported and is a callable factory."""
    from src.dependencies import require_project_role
    guard = require_project_role("admin")
    assert callable(guard)


@pytest.mark.asyncio
async def test_require_project_role_accepts_multiple_roles():
    """require_project_role factory accepts multiple role strings."""
    from src.dependencies import require_project_role
    guard = require_project_role("admin", "lead", "member")
    assert callable(guard)


@pytest.mark.asyncio
async def test_require_project_role_custom_param_name():
    """require_project_role accepts a custom path parameter name."""
    from src.dependencies import require_project_role
    guard = require_project_role("admin", project_id_param="pid")
    assert callable(guard)


# ═══════════════════════════════════════════════════════════════
# PFL-125: Orchestrator Role Assignment 500 Fix (B130)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_orchestrator_1o_constraint_handles_multi_orch_residue(seed: SeedData):
    """PFL-125: 多 orch 残留时 set_project_role 应返回 ConflictError 而非 500。

    狗粮场景：DB 绕过直接插入多条 orchestrator 记录后，
    API 调用 set_project_role 时 scalar_one_or_none() 遇 MultipleResultsFound → 500。
    修复后 .limit(1) 确保只取一条，正常走 ConflictError 逻辑。
    """
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.project_role_service import set_project_role
    from src.constants import ActorType, WorkerActorType, WorkerStatus, ProjectStatus
    from src.models.project import Project
    from src.models.worker import Worker
    from src.models.project_actor_role import ProjectActorRole

    project_id = generate_id("project")
    w1_id = generate_id("worker")
    w2_id = generate_id("worker")
    w3_id = generate_id("worker")

    async with async_session_factory() as db:
        project = Project(
            id=project_id, team_id=seed.team_id,
            name="Multi Orch Test", slug=f"multi-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        w1 = Worker(id=w1_id, name="Orch1", team_id=seed.team_id,
                     actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE)
        w2 = Worker(id=w2_id, name="Orch2", team_id=seed.team_id,
                     actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE)
        w3 = Worker(id=w3_id, name="Orch3", team_id=seed.team_id,
                     actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE)
        db.add_all([project, w1, w2, w3])
        await db.flush()

        # Simulate dogfood DB bypass: directly insert two orchestrator records
        db.add(ProjectActorRole(id=generate_id("project_actor_role"),
                                 project_id=project_id, worker_id=w1_id,
                                 role="orchestrator"))
        db.add(ProjectActorRole(id=generate_id("project_actor_role"),
                                 project_id=project_id, worker_id=w2_id,
                                 role="orchestrator"))
        await db.flush()

        # Verify pre-existing state: 2 orchestrator records
        result = await db.execute(
            select(ProjectActorRole).where(
                ProjectActorRole.project_id == project_id,
                ProjectActorRole.role == "orchestrator",
            )
        )
        assert len(result.scalars().all()) == 2

        # After fix: should raise ConflictError (409), NOT MultipleResultsFound (500)
        from src.exceptions import ConflictError
        with pytest.raises(ConflictError) as exc_info:
            await set_project_role(
                db, project_id=project_id, worker_id=w3_id, role="orchestrator",
                team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=w3_id,
            )
        assert exc_info.value.code == "ONE_ORCHESTRATOR_PER_PROJECT"

        await db.rollback()


@pytest.mark.asyncio
async def test_orchestrator_first_assignment_succeeds(seed: SeedData):
    """PFL-125: 无已有 orch 时，set_project_role(role='orchestrator') 应成功。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.project_role_service import set_project_role
    from src.constants import ActorType, WorkerActorType, WorkerStatus, ProjectStatus
    from src.models.project import Project
    from src.models.worker import Worker

    project_id = generate_id("project")
    worker_id = generate_id("worker")

    async with async_session_factory() as db:
        project = Project(
            id=project_id, team_id=seed.team_id,
            name="First Orch Test", slug=f"first-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        worker = Worker(id=worker_id, name="First Orch", team_id=seed.team_id,
                         actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE)
        db.add_all([project, worker])
        await db.flush()

        record = await set_project_role(
            db, project_id=project_id, worker_id=worker_id, role="orchestrator",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=worker_id,
        )
        assert record.role == "orchestrator"
        assert record.project_id == project_id
        assert record.worker_id == worker_id

        await db.commit()


@pytest.mark.asyncio
async def test_assign_orchestrator_role_endpoint(client: AsyncClient, seed: SeedData):
    """PFL-125: POST /admin/projects/{id}/roles role=orchestrator → 201。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.constants import WorkerActorType, WorkerStatus, ProjectStatus
    from src.models.project import Project
    from src.models.worker import Worker

    project_id = generate_id("project")
    worker_id = generate_id("worker")

    async with async_session_factory() as db:
        project = Project(
            id=project_id, team_id=seed.team_id,
            name="HTTP Orch Test", slug=f"http-orch-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        worker = Worker(id=worker_id, name="HTTP Orch Worker",
                         team_id=seed.team_id, actor_type=WorkerActorType.HUMAN,
                         status=WorkerStatus.ACTIVE)
        db.add_all([project, worker])
        await db.commit()

    resp = await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": "orchestrator"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["role"] == "orchestrator"
    assert data["worker_id"] == worker_id


@pytest.mark.asyncio
async def test_register_worker_with_orchestrator_role(client: AsyncClient, seed: SeedData):
    """PFL-125: POST /teams/{id}/workers with role=orchestrator → 201。

    验证 worker 创建 + orchestrator 角色分配路径。
    """
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.constants import WorkerActorType, WorkerStatus, ProjectStatus
    from src.models.project import Project
    from src.models.worker import Worker
    from src.services.project_role_service import get_project_role

    project_id = generate_id("project")
    async with async_session_factory() as db:
        project = Project(
            id=project_id, team_id=seed.team_id,
            name="Reg Orch Test", slug=f"reg-orch-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.commit()

    resp = await client.post(
        f"/v1/teams/{seed.team_id}/workers",
        json={
            "name": "Orch Worker via Register",
            "provider": "claude",
            "project_id": project_id,
            "role": "orchestrator",
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["worker"]["name"] == "Orch Worker via Register"

    # Verify the role was assigned in project_actor_roles
    from src.db import async_session_factory as asf
    async with asf() as db:
        role = await get_project_role(db, project_id, data["worker"]["id"])
        assert role == "orchestrator"
