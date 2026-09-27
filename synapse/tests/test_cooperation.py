"""P8-B3: Cooperation — 认领 + 分配 + 租约测试。

覆盖:
- 单任务认领（带租约字段 claimed_at、lease_expires_at）
- 批量认领（批次中所有 READY 任务）
- 单任务分配（带租约，Worker）
- 批量分配（多任务，D-P7-023）
- 租约过期检测和释放
- 认领时的乐观锁冲突
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, TaskStatus, WorkerRuntimeStatus
from src.exceptions import ConflictError, NotFoundError
from src.models.worker import Worker
from src.models.batch import Batch
from src.models.member import Member
from src.models.project import Project
from src.models.project_actor_role import ProjectActorRole
from src.models.task import Task
from src.models.team import Team
from src.services.lease_detector import release_expired_leases
from src.services.worker_scheduler import start_task
from src.services.task_service import (
    LEASE_DURATION_SECONDS,
    assign_batch,
    assign_task,
    claim_batch,
    claim_task,
    create_task,
    ready_task,
    task_to_response,
)
from src.utils.id_gen import derive_id, generate_id


# ═══════════════════════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db(app) -> AsyncSession:
    from src.db import async_session_factory
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def seeded(db: AsyncSession) -> dict:
    """为协作测试创建 Team + Project + Member + Worker + Batch。"""
    team_id = generate_id("team")
    project_id = generate_id("project")
    member_id = generate_id("member")
    agent_id = generate_id("worker")
    batch_id = generate_id("batch")

    team = Team(id=team_id, name="协作团队", slug=f"coop-{team_id[-8:]}")
    project = Project(id=project_id, team_id=team_id, name="协作项目", slug=f"coop-{project_id[-8:]}")
    member = Member(id=member_id, team_id=team_id, user_id="user-1", display_name="管理员", role="admin")
    agent = Worker(
        id=agent_id, team_id=team_id, name="Test Worker",
        provider="claude", provider_model="sonnet", status="active",
        registered_by=None, api_key_hash="test-hash", api_key_prefix="sk-test",
    )
    batch = Batch(id=batch_id, project_id=project_id, name="Test Batch", status="open")
    role = ProjectActorRole(id=generate_id("project_actor_role"), project_id=project_id, worker_id=agent_id, role="builder")
    db.add_all([team, project, member, agent, batch, role])
    await db.flush()
    return {
        "team_id": team_id, "project_id": project_id,
        "member_id": member_id, "agent_id": agent_id, "batch_id": batch_id,
    }


async def _create_ready_task(db: AsyncSession, seeded: dict, **kw) -> Task:
    """创建任务并使其就绪。"""
    task = await create_task(
        db, project_id=seeded["project_id"], title=kw.get("title", "Test Task"),
        description=kw.get("description", "测试描述"), priority="p1",
        parent_task_id=None, batch_id=kw.get("batch_id", seeded["batch_id"]),
        estimated_effort=None, tags=None, metadata=None, deadline_at=None,
        verifications=[{"type": "manual", "description": "Verify all checks passed"}],
        actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
    )
    await db.flush()
    task = await ready_task(
        db, task.id, expected_version=task.version_no,
        actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
    )
    await db.flush()
    return task


# ═══════════════════════════════════════════════════════════════════
# 单任务认领
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSingleClaim:
    async def test_claim_sets_lease_fields(self, db: AsyncSession, seeded: dict):
        """认领设置租约字段。"""
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        assert claimed.status == "in_progress"
        assert claimed.owner_type == "worker"
        assert claimed.owner_id == seeded["agent_id"]
        assert claimed.claimed_at is not None
        assert claimed.lease_expires_at is not None
        # 租约应为距今 ~10 分钟
        delta = (claimed.lease_expires_at - claimed.claimed_at).total_seconds()
        assert delta == pytest.approx(LEASE_DURATION_SECONDS, rel=0.1)

    async def test_claim_version_conflict(self, db: AsyncSession, seeded: dict):
        """认领时的版本冲突。"""
        task = await _create_ready_task(db, seeded)
        with pytest.raises(ConflictError, match="VERSION_CONFLICT"):
            await claim_task(
                db, task.id, worker_id=seeded["agent_id"],
                worker_team_id=seeded["team_id"], expected_version=999,
            )

    async def test_claim_already_claimed_by_other(self, db: AsyncSession, seeded: dict):
        """已被其他 Worker 认领的任务不能再被认领。"""
        task = await _create_ready_task(db, seeded)
        await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        # 创建另一个 agent 并尝试认领同一任务
        agent2_id = generate_id("worker")
        agent2 = Worker(
            id=agent2_id, team_id=seeded["team_id"], name="Worker 2",
            provider="claude", provider_model="sonnet", status="active",
            registered_by=None, api_key_hash="hash2", api_key_prefix="sk-2",
        )
        db.add(agent2)
        agent2_role = ProjectActorRole(
            id=generate_id("project_actor_role"),
            project_id=seeded["project_id"], worker_id=agent2_id, role="builder",
        )
        db.add(agent2_role)
        await db.flush()

        with pytest.raises(ConflictError, match="TASK_ALREADY_CLAIMED"):
            await claim_task(
                db, task.id, worker_id=agent2_id,
                worker_team_id=seeded["team_id"], expected_version=task.version_no,
            )

    async def test_claim_response_includes_lease(self, db: AsyncSession, seeded: dict):
        """task_to_response 包含 claimed_at 和 lease_expires_at。"""
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        resp = await task_to_response(claimed, db)
        assert resp["claimed_at"] is not None
        assert resp["lease_expires_at"] is not None
        assert resp["owner_name"] is not None  # P11-B14: owner_name 已富化


# ═══════════════════════════════════════════════════════════════════
# 批量认领
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestBatchClaim:
    async def test_claim_batch_all_ready(self, db: AsyncSession, seeded: dict):
        """认领包含 3 个 READY 任务的批次 → 全部认领。"""
        tasks = []
        for i in range(3):
            t = await _create_ready_task(db, seeded, title=f"任务 {i}")
            tasks.append(t)

        result = await claim_batch(
            db, seeded["batch_id"], worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"],
        )
        await db.flush()

        assert result["claimed_count"] == 3
        assert len(result["task_ids"]) == 3

        # 验证所有任务现在为 IN_PROGRESS 并带租约
        for tid in result["task_ids"]:
            from sqlalchemy import select as sa_select
            stmt = sa_select(Task).where(Task.id == tid)
            t = (await db.execute(stmt)).scalar_one()
            assert t.status == "in_progress"
            assert t.owner_id == seeded["agent_id"]
            assert t.lease_expires_at is not None

    async def test_claim_batch_attaches_active_task(self, db: AsyncSession, seeded: dict):
        """批量认领也挂 active_task_id（P16-B9 PFL-255），否则 state_router 无活可路由。"""
        tasks = [await _create_ready_task(db, seeded, title=f"批量 {i}") for i in range(2)]

        result = await claim_batch(
            db, seeded["batch_id"], worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"],
        )
        await db.flush()

        assert result["claimed_count"] == 2
        worker = await db.get(Worker, seeded["agent_id"])
        assert worker.active_task_id == result["task_ids"][0], (
            "批量认领未把首个任务挂为 active_task_id"
        )
        assert worker.runtime_status == WorkerRuntimeStatus.BUSY

    async def test_claim_batch_no_ready_tasks(self, db: AsyncSession, seeded: dict):
        """认领空批次引发冲突。"""
        # 创建任务但保留在 BACKLOG（不就绪）
        await create_task(
            db, project_id=seeded["project_id"], title="Backlog 任务",
            description="未就绪", priority="p1",
            parent_task_id=None, batch_id=seeded["batch_id"],
            estimated_effort=None, tags=None, metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Verify all checks passed"}],
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
        )
        await db.flush()

        with pytest.raises(ConflictError, match="NO_READY_TASKS_IN_BATCH"):
            await claim_batch(
                db, seeded["batch_id"], worker_id=seeded["agent_id"],
                worker_team_id=seeded["team_id"],
            )

    async def test_claim_batch_nonexistent(self, db: AsyncSession, seeded: dict):
        """认领不存在的批次。"""
        with pytest.raises(NotFoundError):
            await claim_batch(
                db, "nonexistent-batch", worker_id=seeded["agent_id"],
                worker_team_id=seeded["team_id"],
            )

    async def test_claim_batch_inactive_agent(self, db: AsyncSession, seeded: dict):
        """停用 Worker 不能认领。"""
        task = await _create_ready_task(db, seeded)
        # 停用 agent
        agent = await db.get(Worker, seeded["agent_id"])
        agent.status = "inactive"
        await db.flush()

        with pytest.raises(ConflictError, match="WORKER_NOT_ACTIVE"):
            await claim_batch(
                db, seeded["batch_id"], worker_id=seeded["agent_id"],
                worker_team_id=seeded["team_id"],
            )


# ═══════════════════════════════════════════════════════════════════
# 单任务分配（推送）
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSingleAssign:
    async def test_assign_to_agent_sets_lease(self, db: AsyncSession, seeded: dict):
        """分配给 Worker 设置租约。"""
        task = await _create_ready_task(db, seeded)
        assigned = await assign_task(
            db, task.id, owner_type="worker", owner_id=seeded["agent_id"],
            expected_version=task.version_no,
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
        )
        await db.flush()

        assert assigned.status == "in_progress"
        assert assigned.claimed_at is not None
        assert assigned.lease_expires_at is not None

    async def test_assign_to_member_no_lease(self, db: AsyncSession, seeded: dict):
        """Member 分配不设置租约字段。"""
        task = await _create_ready_task(db, seeded)
        assigned = await assign_task(
            db, task.id, owner_type="member", owner_id=seeded["member_id"],
            expected_version=task.version_no,
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
        )
        await db.flush()

        assert assigned.status == "in_progress"
        assert assigned.claimed_at is None
        assert assigned.lease_expires_at is None


# ═══════════════════════════════════════════════════════════════════
# 批量分配
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestBatchAssign:
    async def test_assign_batch_success(self, db: AsyncSession, seeded: dict):
        """批量分配成功。"""
        tasks = []
        for i in range(3):
            t = await _create_ready_task(db, seeded, title=f"批量任务 {i}")
            tasks.append(t)

        result = await assign_batch(
            db, task_ids=[t.id for t in tasks],
            owner_type="worker", owner_id=seeded["agent_id"],
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
        )
        await db.flush()

        assert result["assigned_count"] == 3

    async def test_assign_batch_attaches_active_task(self, db: AsyncSession, seeded: dict):
        """批量分配也挂 active_task_id（P16-B9 PFL-255）。"""
        tasks = [await _create_ready_task(db, seeded, title=f"批量分配 {i}") for i in range(2)]

        result = await assign_batch(
            db, task_ids=[t.id for t in tasks],
            owner_type="worker", owner_id=seeded["agent_id"],
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
            team_id=seeded["team_id"],
        )
        await db.flush()

        assert result["assigned_count"] == 2
        worker = await db.get(Worker, seeded["agent_id"])
        assert worker.active_task_id == result["task_ids"][0], (
            "批量分配未把首个任务挂为 active_task_id"
        )
        assert worker.runtime_status == WorkerRuntimeStatus.BUSY

    async def test_assign_batch_too_large(self, db: AsyncSession, seeded: dict):
        """批量分配超过上限。"""
        with pytest.raises(ConflictError, match="BATCH_TOO_LARGE"):
            await assign_batch(
                db, task_ids=[f"task-{i}" for i in range(25)],
                owner_type="worker", owner_id=seeded["agent_id"],
                actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
            )

    async def test_assign_batch_empty(self, db: AsyncSession, seeded: dict):
        """空任务列表。"""
        with pytest.raises(ConflictError, match="EMPTY_TASK_LIST"):
            await assign_batch(
                db, task_ids=[],
                owner_type="worker", owner_id=seeded["agent_id"],
                actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
            )

    async def test_assign_batch_nonexistent_agent(self, db: AsyncSession, seeded: dict):
        """分配给不存在的 Worker。"""
        task = await _create_ready_task(db, seeded)
        with pytest.raises(NotFoundError):
            await assign_batch(
                db, task_ids=[task.id],
                owner_type="worker", owner_id="nonexistent",
                actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"), team_id=seeded["team_id"],
            )


# ═══════════════════════════════════════════════════════════════════
# 租约过期
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestLeaseExpiry:
    async def test_expired_lease_releases_task(self, db: AsyncSession, seeded: dict):
        """租约过期的任务释放回 READY。"""
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        # 手动使租约过期
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db.flush()

        # 运行租约检测器
        result = await release_expired_leases(db)
        await db.flush()

        assert result["released_count"] == 1
        assert task.id in result["released_task_ids"]

        # 任务应回 READY，所有权清除
        # 从 DB 重新读取
        from sqlalchemy import select as sa_select
        stmt = sa_select(Task).where(Task.id == task.id)
        released = (await db.execute(stmt)).scalar_one()
        assert released.status == "ready"
        assert released.owner_id is None
        assert released.owner_type is None
        assert released.claimed_at is None
        assert released.lease_expires_at is None

    async def test_active_lease_not_released(self, db: AsyncSession, seeded: dict):
        """有效（未过期）租约的任务不应被释放。"""
        task = await _create_ready_task(db, seeded)
        await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        result = await release_expired_leases(db)
        assert result["released_count"] == 0

    async def test_expired_lease_alive_worker_not_released(self, db: AsyncSession, seeded: dict):
        """PFL-267: 租约过期但 owner worker 心跳仍新鲜 → 免死守卫跳过，不释放。

        卡在门禁 / 干长活的活 builder 不得被 lease 回收（PFL-245 候选③）。
        """
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        # 租约过期，但 worker 心跳新鲜（活着但在干长活 / 卡门禁）
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        worker = await db.get(Worker, seeded["agent_id"])
        worker.last_heartbeat_at = datetime.now(timezone.utc)
        await db.flush()

        result = await release_expired_leases(db)
        assert result["released_count"] == 0

    async def test_expired_lease_offline_worker_released(self, db: AsyncSession, seeded: dict):
        """PFL-267: 心跳虽新鲜但已 OFFLINE 的 owner worker → 视为失联，正常释放。"""
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        worker = await db.get(Worker, seeded["agent_id"])
        worker.last_heartbeat_at = datetime.now(timezone.utc)  # 心跳新鲜
        worker.runtime_status = WorkerRuntimeStatus.OFFLINE       # 但已被判 OFFLINE
        await db.flush()

        result = await release_expired_leases(db)
        assert result["released_count"] == 1

    async def test_expired_lease_human_owner_not_released(self, db: AsyncSession, seeded: dict):
        """P17-B2 (PFL-245): 租约过期但 owner 是 human → 免死，不释放。

        人类认领者没有心跳/续期机制，lease 过期不应把活人误判僵尸（PFL-245
        根因：claim 写 600s lease 但 human 永不续期 → 原实现 10 分钟后被踢）。
        """
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["member_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
            actor_type=ActorType.HUMAN,
        )
        await db.flush()
        assert claimed.owner_type == "human"

        # 手动使租约过期
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db.flush()

        result = await release_expired_leases(db)
        await db.flush()

        assert task.id not in result["released_task_ids"]

        from sqlalchemy import select as sa_select
        stmt = sa_select(Task).where(Task.id == task.id)
        released = (await db.execute(stmt)).scalar_one()
        assert released.status == "in_progress"
        assert released.owner_type == "human"
        assert released.owner_id == seeded["member_id"]
        assert released.lease_expires_at is not None  # 免死不释放 → lease 字段原样保留

    async def test_start_task_clears_lease(self, db: AsyncSession, seeded: dict):
        """PFL-267: Worker 真正开工即清 lease — lease 语义收敛为 claim→start 窗口。"""
        task = await _create_ready_task(db, seeded)
        await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()
        assert task.lease_expires_at is not None

        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()
        await db.refresh(task)
        assert task.lease_expires_at is None

    async def test_multiple_expired_leases(self, db: AsyncSession, seeded: dict):
        """多个过期租约 → 全部释放。"""
        tasks = []
        for i in range(3):
            t = await _create_ready_task(db, seeded, title=f"租约任务 {i}")
            claimed = await claim_task(
                db, t.id, worker_id=seeded["agent_id"],
                worker_team_id=seeded["team_id"], expected_version=t.version_no,
            )
            await db.flush()
            # 使所有租约过期
            claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=60)
            await db.flush()
            tasks.append(t)

        result = await release_expired_leases(db)
        assert result["released_count"] == 3

    async def test_completed_task_not_affected(self, db: AsyncSession, seeded: dict):
        """已完成但有旧租约的任务不应被释放。"""
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        # 模拟完成 — 设置状态为 completed，但保留旧租约
        claimed.status = "completed"
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db.flush()

        result = await release_expired_leases(db)
        assert result["released_count"] == 0  # 仅扫描 IN_PROGRESS 状态

    async def test_released_task_can_be_reclaimed(self, db: AsyncSession, seeded: dict):
        """租约过期释放后，任务可被另一个 Worker 认领。"""
        task = await _create_ready_task(db, seeded)
        claimed = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()

        # 使租约过期
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db.flush()

        # 释放
        result = await release_expired_leases(db)
        await db.flush()
        assert result["released_count"] == 1

        # 创建第二个 agent
        agent2_id = generate_id("worker")
        agent2 = Worker(
            id=agent2_id, team_id=seeded["team_id"], name="Worker 2",
            provider="claude", provider_model="sonnet", status="active",
            registered_by=None, api_key_hash="hash2", api_key_prefix="sk-2",
        )
        db.add(agent2)
        agent2_role = ProjectActorRole(
            id=generate_id("project_actor_role"),
            project_id=seeded["project_id"], worker_id=agent2_id, role="builder",
        )
        db.add(agent2_role)
        await db.flush()

        # Worker 2 重新认领
        from sqlalchemy import select as sa_select
        stmt = sa_select(Task).where(Task.id == task.id)
        released = (await db.execute(stmt)).scalar_one()
        reclaimed = await claim_task(
            db, task.id, worker_id=agent2_id,
            worker_team_id=seeded["team_id"], expected_version=released.version_no,
        )
        await db.flush()

        assert reclaimed.status == "in_progress"
        assert reclaimed.owner_id == agent2_id
        assert reclaimed.claimed_at is not None
        assert reclaimed.lease_expires_at is not None
