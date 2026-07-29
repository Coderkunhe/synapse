"""P10-B25: Workflow + WorkflowRole Service 层测试 — CRUD + 事件记录."""

from __future__ import annotations

import pytest

from tests.conftest import SeedData


# ═══════════════════════════════════════════════════════════════
# Workflow CRUD Tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_workflow(seed: SeedData):
    """create_workflow 创建 Workflow 并记录事件。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import create_workflow, get_workflow
    from src.constants import ActorType
    from src.models.project import Project
    from src.constants import ProjectStatus

    project_id = generate_id("project")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()

        workflow = await create_workflow(
            db,
            project_id=project_id,
            name="P10 Architecture",
            description="Upgrade auth system",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )

        assert workflow.id.startswith("wfl_")
        assert workflow.project_id == project_id
        assert workflow.name == "P10 Architecture"
        assert workflow.description == "Upgrade auth system"
        assert workflow.status == "active"

        # 可查询
        fetched = await get_workflow(db, workflow.id)
        assert fetched is not None
        assert fetched.id == workflow.id

        await db.rollback()


@pytest.mark.asyncio
async def test_get_workflow_none_for_unknown_id(seed: SeedData):
    """get_workflow 对不存在的 ID 返回 None。"""
    from src.db import async_session_factory
    from src.services.workflow_role_service import get_workflow

    async with async_session_factory() as db:
        wf = await get_workflow(db, "wfl_nonexistent")
        assert wf is None


@pytest.mark.asyncio
async def test_list_workflows(seed: SeedData):
    """list_workflows 列出 Project 中所有 Workflow。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import (
        create_workflow,
        list_workflows,
    )
    from src.constants import ActorType
    from src.models.project import Project
    from src.constants import ProjectStatus

    project_id = generate_id("project")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()

        wf1 = await create_workflow(
            db, project_id=project_id, name="Workflow A",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        wf2 = await create_workflow(
            db, project_id=project_id, name="Workflow B",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        workflows = await list_workflows(db, project_id)
        assert len(workflows) == 2
        # 按创建时间倒序 — wf2 排在 wf1 前面
        assert workflows[0].id == wf2.id
        assert workflows[1].id == wf1.id

        await db.rollback()


@pytest.mark.asyncio
async def test_list_workflows_empty_project(seed: SeedData):
    """list_workflows 对没有 Workflow 的 Project 返回空列表。"""
    from src.db import async_session_factory
    from src.services.workflow_role_service import list_workflows

    async with async_session_factory() as db:
        workflows = await list_workflows(db, "proj_nonexistent")
        assert workflows == []


@pytest.mark.asyncio
async def test_update_workflow(seed: SeedData):
    """update_workflow 部分更新字段。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import (
        create_workflow,
        update_workflow,
    )
    from src.constants import ActorType
    from src.models.project import Project
    from src.constants import ProjectStatus

    project_id = generate_id("project")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()

        wf = await create_workflow(
            db, project_id=project_id, name="Original",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        updated = await update_workflow(
            db,
            workflow_id=wf.id,
            name="Updated Name",
            description="New desc",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )
        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.description == "New desc"
        # status unchanged
        assert updated.status == "active"

        await db.rollback()


@pytest.mark.asyncio
async def test_update_workflow_nonexistent(seed: SeedData):
    """update_workflow 对不存在的 workflow 返回 None。"""
    from src.db import async_session_factory
    from src.services.workflow_role_service import update_workflow
    from src.constants import ActorType

    async with async_session_factory() as db:
        result = await update_workflow(
            db, workflow_id="wfl_nonexistent", name="X",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert result is None


@pytest.mark.asyncio
async def test_update_workflow_no_changes(seed: SeedData):
    """update_workflow 无变更时返回原 Workflow 不记录事件。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import (
        create_workflow,
        update_workflow,
    )
    from src.constants import ActorType
    from src.models.project import Project
    from src.constants import ProjectStatus

    project_id = generate_id("project")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()

        wf = await create_workflow(
            db, project_id=project_id, name="Stable",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        # 传入全部 None — 不触发更新
        result = await update_workflow(
            db, workflow_id=wf.id,
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert result is not None
        assert result.id == wf.id

        await db.rollback()


@pytest.mark.asyncio
async def test_complete_workflow(seed: SeedData):
    """complete_workflow 将 status 设为 completed 并记录事件。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import (
        create_workflow,
        complete_workflow,
    )
    from src.constants import ActorType
    from src.models.project import Project
    from src.constants import ProjectStatus

    project_id = generate_id("project")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Test Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()

        wf = await create_workflow(
            db, project_id=project_id, name="To Complete",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert wf.status == "active"

        result = await complete_workflow(
            db,
            workflow_id=wf.id,
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )
        assert result is not None
        assert result.status == "completed"

        await db.rollback()


@pytest.mark.asyncio
async def test_complete_workflow_nonexistent(seed: SeedData):
    """complete_workflow 对不存在的 workflow 返回 None。"""
    from src.db import async_session_factory
    from src.services.workflow_role_service import complete_workflow
    from src.constants import ActorType

    async with async_session_factory() as db:
        result = await complete_workflow(
            db, workflow_id="wfl_nonexistent",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════
# WorkflowRole Tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_assign_workflow_role_new(seed: SeedData):
    """assign_workflow_role 为新 Worker 分配角色。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import (
        assign_workflow_role,
        list_workflow_roles,
    )
    from src.constants import ActorType, WorkerActorType, WorkerStatus
    from src.models.project import Project
    from src.models.workflow import Workflow
    from src.models.worker import Worker

    async with async_session_factory() as db:
        # 直接创建 Workflow 行（跳过服务层事件以简化，或用 ORM 直接 insert）
        wf_id = generate_id("workflow")
        worker_id = generate_id("worker")
        proj_id = generate_id("project")
        proj = Project(id=proj_id, team_id=seed.team_id, name="Test Project",
                       slug=f"test-{proj_id[-8:]}", status="active")
        db.add(proj)
        await db.flush()

        workflow = Workflow(
            id=wf_id,
            project_id=proj_id,
            name="Test WF",
            status="active",
        )
        worker = Worker(
            id=worker_id,
            name="Test Worker",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add_all([workflow, worker])
        await db.flush()

        record = await assign_workflow_role(
            db,
            workflow_id=wf_id,
            worker_id=worker_id,
            role="builder",
            team_id=seed.team_id,
            actor_type=ActorType.HUMAN,
            actor_id=seed.worker_id,
        )
        assert record.id.startswith("wfr_")
        assert record.workflow_id == wf_id
        assert record.worker_id == worker_id
        assert record.role == "builder"

        # 列表可见
        roles = await list_workflow_roles(db, wf_id)
        assert len(roles) == 1
        assert roles[0][1] == "builder"

        await db.rollback()


@pytest.mark.asyncio
async def test_assign_workflow_role_upsert(seed: SeedData):
    """assign_workflow_role 对已有记录触发更新。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import assign_workflow_role
    from src.constants import ActorType, WorkerActorType, WorkerStatus
    from src.models.project import Project
    from src.models.workflow import Workflow
    from src.models.worker import Worker

    async with async_session_factory() as db:
        wf_id = generate_id("workflow")
        worker_id = generate_id("worker")
        proj_id = generate_id("project")
        proj = Project(id=proj_id, team_id=seed.team_id, name="Test Project",
                       slug=f"test-{proj_id[-8:]}", status="active")
        db.add(proj)
        await db.flush()

        workflow = Workflow(
            id=wf_id,
            project_id=proj_id,
            name="Test WF",
            status="active",
        )
        worker = Worker(
            id=worker_id,
            name="Test Worker",
            team_id=seed.team_id,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
        )
        db.add_all([workflow, worker])
        await db.flush()

        # 首次分配 builder
        r1 = await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id, role="builder",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert r1.role == "builder"

        # 更新为 orchestrator
        r2 = await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id, role="orchestrator",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert r2.role == "orchestrator"
        assert r2.id == r1.id  # 同一条记录

        await db.rollback()


@pytest.mark.asyncio
async def test_assign_workflow_role_same_role_noop(seed: SeedData):
    """assign_workflow_role 角色未变时不触发事件。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import assign_workflow_role
    from src.constants import ActorType, WorkerActorType, WorkerStatus
    from src.models.project import Project
    from src.models.workflow import Workflow
    from src.models.worker import Worker

    async with async_session_factory() as db:
        wf_id = generate_id("workflow")
        worker_id = generate_id("worker")
        proj_id = generate_id("project")
        proj = Project(id=proj_id, team_id=seed.team_id, name="Test Project",
                       slug=f"test-{proj_id[-8:]}", status="active")
        db.add(proj)
        await db.flush()

        workflow = Workflow(
            id=wf_id, project_id=proj_id, name="Test WF", status="active",
        )
        worker = Worker(
            id=worker_id, name="Test Worker",
            team_id=seed.team_id, actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE,
        )
        db.add_all([workflow, worker])
        await db.flush()

        r1 = await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id, role="orchestrator",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        # 再次用相同角色调用 — 应返回同一记录无修改
        r2 = await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id, role="orchestrator",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert r2.id == r1.id
        assert r2.role == "orchestrator"

        await db.rollback()


@pytest.mark.asyncio
async def test_list_workflow_roles_empty(seed: SeedData):
    """list_workflow_roles 对没有角色的 Workflow 返回空列表。"""
    from src.db import async_session_factory
    from src.services.workflow_role_service import list_workflow_roles

    async with async_session_factory() as db:
        roles = await list_workflow_roles(db, "wfl_nonexistent")
        assert roles == []


@pytest.mark.asyncio
async def test_list_workflow_roles_multiple(seed: SeedData):
    """list_workflow_roles 返回所有角色，按 Worker name 排序。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import (
        assign_workflow_role,
        list_workflow_roles,
    )
    from src.constants import ActorType, WorkerActorType, WorkerStatus
    from src.models.project import Project
    from src.models.workflow import Workflow
    from src.models.worker import Worker

    async with async_session_factory() as db:
        wf_id = generate_id("workflow")
        proj_id = generate_id("project")
        proj = Project(id=proj_id, team_id=seed.team_id, name="Test Project",
                       slug=f"test-{proj_id[-8:]}", status="active")
        db.add(proj)
        await db.flush()

        workflow = Workflow(
            id=wf_id, project_id=proj_id, name="Test WF", status="active",
        )
        db.add(workflow)
        await db.flush()

        # 创建两个 Worker — Charlie 排在 Alice 后面
        w_alice = Worker(id=generate_id("worker"), name="Alice",
                         team_id=seed.team_id, actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE)
        w_charlie = Worker(id=generate_id("worker"), name="Charlie",
                           team_id=seed.team_id, actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE)
        db.add_all([w_alice, w_charlie])
        await db.flush()

        await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=w_charlie.id, role="builder",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=w_alice.id, role="orchestrator",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        roles = await list_workflow_roles(db, wf_id)
        assert len(roles) == 2
        assert roles[0][0].name == "Alice"   # 按 name 排序
        assert roles[0][1] == "orchestrator"
        assert roles[1][0].name == "Charlie"
        assert roles[1][1] == "builder"

        await db.rollback()


@pytest.mark.asyncio
async def test_revoke_workflow_role(seed: SeedData):
    """revoke_workflow_role 移除角色记录。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.services.workflow_role_service import (
        assign_workflow_role,
        list_workflow_roles,
        revoke_workflow_role,
    )
    from src.constants import ActorType, WorkerActorType, WorkerStatus
    from src.models.project import Project
    from src.models.workflow import Workflow
    from src.models.worker import Worker

    async with async_session_factory() as db:
        wf_id = generate_id("workflow")
        worker_id = generate_id("worker")
        proj_id = generate_id("project")
        proj = Project(id=proj_id, team_id=seed.team_id, name="Test Project",
                       slug=f"test-{proj_id[-8:]}", status="active")
        db.add(proj)
        await db.flush()

        workflow = Workflow(
            id=wf_id, project_id=proj_id, name="Test WF", status="active",
        )
        worker = Worker(
            id=worker_id, name="Test Worker",
            team_id=seed.team_id, actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE,
        )
        db.add_all([workflow, worker])
        await db.flush()

        await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id, role="builder",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        # 移除
        removed = await revoke_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id,
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert removed is True

        # 列表为空
        roles = await list_workflow_roles(db, wf_id)
        assert roles == []

        await db.rollback()


@pytest.mark.asyncio
async def test_revoke_workflow_role_nonexistent(seed: SeedData):
    """revoke_workflow_role 对不存在的记录返回 False。"""
    from src.db import async_session_factory
    from src.services.workflow_role_service import revoke_workflow_role
    from src.constants import ActorType

    async with async_session_factory() as db:
        removed = await revoke_workflow_role(
            db, workflow_id="wfl_x", worker_id="wrk_x",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        assert removed is False


# ═══════════════════════════════════════════════════════════════
# Event Coverage
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_workflow_events_created_on_crud(seed: SeedData):
    """Workflow CRUD 操作产生正确的事件类型。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.models.project import Project
    from src.constants import ProjectStatus, ActorType
    from src.services.workflow_role_service import (
        create_workflow,
        update_workflow,
        complete_workflow,
    )
    from sqlalchemy import select
    from src.models.event import Event

    project_id = generate_id("project")

    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Event Project",
            slug=f"test-{project_id[-8:]}",
            status=ProjectStatus.ACTIVE,
        )
        db.add(project)
        await db.flush()

        # Create
        wf = await create_workflow(
            db, project_id=project_id, name="Event WF",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        # Update
        await update_workflow(
            db, workflow_id=wf.id, name="Updated WF",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        # Complete
        await complete_workflow(
            db, workflow_id=wf.id,
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        # 查询事件
        result = await db.execute(
            select(Event)
            .where(Event.target_id == wf.id)
            .order_by(Event.created_at.asc())
        )
        events = result.scalars().all()

        event_types = [e.event_type for e in events]
        assert "workflow.created" in event_types
        assert "workflow.updated" in event_types
        assert "workflow.completed" in event_types

        await db.rollback()


@pytest.mark.asyncio
async def test_workflow_role_events(seed: SeedData):
    """WorkflowRole 分配/变更/撤销 产生正确的事件类型。"""
    from src.db import async_session_factory
    from src.utils.id_gen import generate_id
    from src.constants import ActorType, WorkerActorType, WorkerStatus
    from src.models.project import Project
    from src.models.workflow import Workflow
    from src.models.worker import Worker
    from src.services.workflow_role_service import (
        assign_workflow_role,
        revoke_workflow_role,
    )
    from sqlalchemy import select
    from src.models.event import Event

    async with async_session_factory() as db:
        wf_id = generate_id("workflow")
        worker_id = generate_id("worker")
        proj_id = generate_id("project")
        proj = Project(id=proj_id, team_id=seed.team_id, name="Test Project",
                       slug=f"test-{proj_id[-8:]}", status="active")
        db.add(proj)
        await db.flush()

        workflow = Workflow(
            id=wf_id, project_id=proj_id, name="Event WF", status="active",
        )
        worker = Worker(
            id=worker_id, name="Event Worker",
            team_id=seed.team_id, actor_type=WorkerActorType.HUMAN, status=WorkerStatus.ACTIVE,
        )
        db.add_all([workflow, worker])
        await db.flush()

        # Assign
        rec = await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id, role="builder",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        # Change
        await assign_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id, role="orchestrator",
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )
        # Revoke
        await revoke_workflow_role(
            db, workflow_id=wf_id, worker_id=worker_id,
            team_id=seed.team_id, actor_type=ActorType.HUMAN, actor_id=seed.worker_id,
        )

        # 查询 WorkflowRole 事件
        result = await db.execute(
            select(Event)
            .where(Event.target_id == rec.id)
            .order_by(Event.created_at.asc())
        )
        events = result.scalars().all()

        event_types = [e.event_type for e in events]
        assert "workflow_role.assigned" in event_types
        assert "workflow_role.changed" in event_types

        await db.rollback()
