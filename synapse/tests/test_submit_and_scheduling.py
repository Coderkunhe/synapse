"""P8-B4: Cooperation — 提交 + Worker 调度测试。

覆盖:
- 带 apply_transition + worker 清理的提交流程
- Worker 调度器: get_next_task（FIFO）、start_task、finish_current_task
- Worker 主动状态验证
- 提交所有权强制执行
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import WorkerRuntimeStatus, TaskStatus
from src.exceptions import ConflictError, ForbiddenError, NotFoundError
from src.models.worker import Worker
from src.models.batch import Batch
from src.models.member import Member
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team
from src.services.task_service import (
    claim_task,
    create_task,
    ready_task,
    submit_task,
    task_to_response,
)
from src.services.worker_scheduler import (
    finish_current_task,
    get_next_task,
    get_owned_tasks,
    start_task,
    validate_task_active,
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
    """为 B4 测试创建 Team + Project + Member + Worker + Batch。"""
    team_id = generate_id("team")
    project_id = generate_id("project")
    member_id = generate_id("member")
    agent_id = generate_id("worker")
    batch_id = generate_id("batch")

    team = Team(id=team_id, name="B4 Team", slug=f"b4-{team_id[-8:]}")
    project = Project(
        id=project_id, team_id=team_id, name="B4 Project",
        slug=f"b4-{project_id[-8:]}",
    )
    member = Member(
        id=member_id, team_id=team_id, user_id="user-1",
        display_name="创建者", role="admin",
    )
    agent = Worker(
        id=agent_id, team_id=team_id, name="Test Worker",
        provider="claude", provider_model="sonnet", status="active",
        registered_by=None, api_key_hash="test-hash",
        api_key_prefix="sk-test",
        runtime_status=WorkerRuntimeStatus.IDLE,
    )
    batch = Batch(
        id=batch_id, project_id=project_id, name="B4 Batch", status="open",
    )
    db.add_all([team, project, member, agent, batch])
    await db.flush()
    return {
        "team_id": team_id, "project_id": project_id,
        "member_id": member_id, "agent_id": agent_id, "batch_id": batch_id,
    }


async def _create_ready_claimed_task(
    db: AsyncSession, seeded: dict, **kw
) -> Task:
    """创建任务、使其就绪并认领 — 返回状态为 IN_PROGRESS 的任务。"""
    task = await create_task(
        db,
        project_id=seeded["project_id"],
        title=kw.get("title", "Test Task"),
        description=kw.get("description", "测试描述"),
        priority="p1",
        parent_task_id=None,
        batch_id=kw.get("batch_id", seeded["batch_id"]),
        estimated_effort=None,
        tags=None,
        metadata=None,
        deadline_at=None,
        verifications=[{"type": "manual", "description": "Verify all checks passed"}],
        actor_type="human",
        actor_id=derive_id(seeded["member_id"], "worker"),
        team_id=seeded["team_id"],
    )
    await db.flush()
    task = await ready_task(
        db, task.id, expected_version=task.version_no,
        actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
        team_id=seeded["team_id"],
    )
    await db.flush()
    task = await claim_task(
        db, task.id, worker_id=seeded["agent_id"],
        worker_team_id=seeded["team_id"], expected_version=task.version_no,
    )
    await db.flush()
    return task


# ═══════════════════════════════════════════════════════════════════
# 提交流程（B4 增强）
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestSubmitTask:
    async def test_submit_transitions_to_in_verification(
        self, db: AsyncSession, seeded: dict,
    ):
        """提交将任务转换到 IN_VERIFICATION 并记录事件。"""
        task = await _create_ready_claimed_task(db, seeded)

        submitted = await submit_task(
            db, task.id, summary="全部完成", evidence={"output_access": {"type": "inline", "value": "test"}},
            verification_results=[], expected_version=task.version_no,
            actor_type="worker", actor_id=seeded["agent_id"],
            team_id=seeded["team_id"],
        )
        await db.flush()

        assert submitted.status == "in_verification"

    async def test_submit_clears_worker_active_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """B4: Worker 提交时，Worker 的 active_task_id 被清除。"""
        task = await _create_ready_claimed_task(db, seeded)

        # 设置 Worker 为 BUSY 并关联此活跃任务
        agent = await db.get(Worker, seeded["agent_id"])
        agent.runtime_status = WorkerRuntimeStatus.BUSY
        agent.active_task_id = task.id
        await db.flush()

        await submit_task(
            db, task.id, summary="完成", evidence={"output_access": {"type": "inline", "value": "test"}},
            verification_results=[], expected_version=task.version_no,
            actor_type="worker", actor_id=seeded["agent_id"],
            team_id=seeded["team_id"],
        )
        await db.flush()

        # Worker 应为 IDLE 且无活跃任务
        await db.refresh(agent)
        assert agent.runtime_status == WorkerRuntimeStatus.IDLE
        assert agent.active_task_id is None

    async def test_submit_member_does_not_affect_worker(
        self, db: AsyncSession, seeded: dict,
    ):
        """Member 提交不影响 Worker 运行时状态。"""
        task = await _create_ready_claimed_task(db, seeded)

        # 分配给 member 而非 agent
        task.owner_type = "member"
        task.owner_id = seeded["member_id"]
        await db.flush()

        # 以 member 身份提交
        submitted = await submit_task(
            db, task.id, summary="人工完成", evidence={"output_access": {"type": "inline", "value": "test"}},
            verification_results=[], expected_version=task.version_no,
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
            team_id=seeded["team_id"],
        )
        assert submitted.status == "in_verification"
        # Worker 运行时不应受影响
        agent = await db.get(Worker, seeded["agent_id"])
        assert agent.runtime_status == WorkerRuntimeStatus.IDLE

    async def test_submit_not_owner_fails(
        self, db: AsyncSession, seeded: dict,
    ):
        """只有任务所有者可以提交。"""
        task = await _create_ready_claimed_task(db, seeded)

        # 创建另一个 agent
        agent2_id = generate_id("worker")
        agent2 = Worker(
            id=agent2_id, team_id=seeded["team_id"], name="Worker 2",
            provider="claude", provider_model="sonnet", status="active",
            registered_by=None, api_key_hash="h2",
            api_key_prefix="sk-2",
        )
        db.add(agent2)
        await db.flush()

        with pytest.raises(ForbiddenError, match="NOT_TASK_OWNER"):
            await submit_task(
                db, task.id, summary="盗取", evidence={"output_access": {"type": "inline", "value": "test"}},
                verification_results=[], expected_version=task.version_no,
                actor_type="worker", actor_id=agent2_id,
                team_id=seeded["team_id"],
            )

    async def test_submit_wrong_state_fails(
        self, db: AsyncSession, seeded: dict,
    ):
        """不能提交非 IN_PROGRESS 状态的任务。"""
        task = await _create_ready_claimed_task(db, seeded)

        # 第一次提交成功
        await submit_task(
            db, task.id, summary="第一次", evidence={"output_access": {"type": "inline", "value": "test"}},
            verification_results=[], expected_version=task.version_no,
            actor_type="worker", actor_id=seeded["agent_id"],
            team_id=seeded["team_id"],
        )
        await db.flush()

        # 第二次提交应失败（已为 IN_VERIFICATION）
        from src.exceptions import InvalidStateTransition
        with pytest.raises(InvalidStateTransition):
            await submit_task(
                db, task.id, summary="重复", evidence={"output_access": {"type": "inline", "value": "test"}},
                verification_results=[], expected_version=task.version_no,
                actor_type="worker", actor_id=seeded["agent_id"],
                team_id=seeded["team_id"],
            )

    async def test_submit_version_conflict(
        self, db: AsyncSession, seeded: dict,
    ):
        """提交时的版本冲突被拒绝。"""
        task = await _create_ready_claimed_task(db, seeded)
        with pytest.raises(ConflictError, match="VERSION_CONFLICT"):
            await submit_task(
                db, task.id, summary="过期", evidence={"output_access": {"type": "inline", "value": "test"}},
                verification_results=[], expected_version=999,
                actor_type="worker", actor_id=seeded["agent_id"],
                team_id=seeded["team_id"],
            )


# ═══════════════════════════════════════════════════════════════════
# Worker 调度器 — FIFO 队列
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestGetNextTask:
    async def test_returns_active_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """get_next_task 返回当前活跃任务。"""
        task = await _create_ready_claimed_task(db, seeded)

        # 设为活跃
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        next_task = await get_next_task(db, seeded["agent_id"])
        assert next_task is not None
        assert next_task.id == task.id

    async def test_returns_in_progress_when_no_active(
        self, db: AsyncSession, seeded: dict,
    ):
        """无活跃任务时，返回第一个已认领的 IN_PROGRESS 任务。"""
        task = await _create_ready_claimed_task(db, seeded)
        # 不设置活跃 — 队列仍应返回它

        next_task = await get_next_task(db, seeded["agent_id"])
        assert next_task is not None
        assert next_task.id == task.id
        assert next_task.status == "in_progress"

    async def test_skips_paused_tasks(
        self, db: AsyncSession, seeded: dict,
    ):
        """PAUSED 任务被排除在队列外（规则 3）。"""
        from src.services.task_service import pause_task

        task = await _create_ready_claimed_task(db, seeded)
        await pause_task(
            db, task.id, reason="暂停", expected_version=task.version_no,
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
            team_id=seeded["team_id"],
        )
        await db.flush()

        next_task = await get_next_task(db, seeded["agent_id"])
        assert next_task is None  # 无可执行任务

    async def test_skips_cancelled_tasks(
        self, db: AsyncSession, seeded: dict,
    ):
        """CANCELLED 任务被排除在队列外。"""
        from src.services.task_service import terminate_task

        task = await _create_ready_claimed_task(db, seeded)
        await terminate_task(
            db, task.id, reason="已过时", expected_version=task.version_no,
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
            team_id=seeded["team_id"],
        )
        await db.flush()

        next_task = await get_next_task(db, seeded["agent_id"])
        assert next_task is None

    async def test_fifo_in_progress_before_rejected(
        self, db: AsyncSession, seeded: dict,
    ):
        """规则 4: IN_PROGRESS 任务排在 REJECTED 之前返回。"""
        # 创建两个任务
        t1 = await _create_ready_claimed_task(db, seeded, title="第一个")
        t2 = await _create_ready_claimed_task(db, seeded, title="第二个")

        # 拒绝 t1（模拟验证拒绝）
        t1.status = "rejected"
        t1.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        # t2 保持 IN_PROGRESS，认领时间稍晚
        t2.claimed_at = datetime.now(timezone.utc)
        await db.flush()

        # 清除任何活跃任务
        agent = await db.get(Worker, seeded["agent_id"])
        agent.active_task_id = None
        await db.flush()

        # 应返回 t2（IN_PROGRESS）而非 t1（REJECTED）
        next_task = await get_next_task(db, seeded["agent_id"])
        assert next_task is not None
        assert next_task.id == t2.id
        assert next_task.status == "in_progress"

    async def test_returns_none_when_no_tasks(
        self, db: AsyncSession, seeded: dict,
    ):
        """没有已认领任务的 Worker 返回 None。"""
        # Worker 未认领任何任务
        next_task = await get_next_task(db, seeded["agent_id"])
        assert next_task is None


@pytest.mark.asyncio
class TestStartFinishTask:
    async def test_start_sets_busy_and_active_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """start_task 设置 BUSY + active_task_id。"""
        task = await _create_ready_claimed_task(db, seeded)

        agent = await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        assert agent.runtime_status == WorkerRuntimeStatus.BUSY
        assert agent.active_task_id == task.id
        assert agent.last_progress_at is not None

    async def test_start_unowned_task_fails(
        self, db: AsyncSession, seeded: dict,
    ):
        """不能启动非此 Worker 拥有的任务。"""
        # 创建由 member 而非 agent 拥有的任务
        task = await create_task(
            db, project_id=seeded["project_id"], title="Member 任务",
            description="由 member 拥有", priority="p1",
            parent_task_id=None, batch_id=seeded["batch_id"],
            estimated_effort=None, tags=None, metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Verify all checks passed"}],
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
            team_id=seeded["team_id"],
        )
        await db.flush()

        with pytest.raises(ConflictError, match="TASK_NOT_OWNED_BY_WORKER"):
            await start_task(db, seeded["agent_id"], task.id)

    async def test_finish_clears_to_idle(
        self, db: AsyncSession, seeded: dict,
    ):
        """finish_current_task 清除 active_task_id → IDLE。"""
        task = await _create_ready_claimed_task(db, seeded)
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        agent = await finish_current_task(db, seeded["agent_id"])
        await db.flush()

        assert agent.runtime_status == WorkerRuntimeStatus.IDLE
        assert agent.active_task_id is None

    async def test_get_owned_tasks_returns_queue(
        self, db: AsyncSession, seeded: dict,
    ):
        """get_owned_tasks 以 FIFO 顺序返回所有已拥有任务。"""
        t1 = await _create_ready_claimed_task(db, seeded, title="第一个")
        t2 = await _create_ready_claimed_task(db, seeded, title="第二个")
        t1.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        t2.claimed_at = datetime.now(timezone.utc)
        await db.flush()

        owned = await get_owned_tasks(db, seeded["agent_id"])
        assert len(owned) == 2
        # IN_PROGRESS 任务按 claimed_at 排序
        assert owned[0].id == t1.id
        assert owned[1].id == t2.id


# ═══════════════════════════════════════════════════════════════════
# 主动状态验证
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestValidateTaskActive:
    async def test_ok_when_task_in_progress(
        self, db: AsyncSession, seeded: dict,
    ):
        """IN_PROGRESS 状态的活动任务验证通过。"""
        task = await _create_ready_claimed_task(db, seeded)
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        result = await validate_task_active(db, seeded["agent_id"])
        assert result["ok"] is True

    async def test_ok_when_no_active_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """无活动任务的 Worker 始终正常。"""
        result = await validate_task_active(db, seeded["agent_id"])
        assert result["ok"] is True
        assert result["reason"] == "no_active_task"

    async def test_detects_paused_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """任务 PAUSED 时 Worker 应停止。"""
        from src.services.task_service import pause_task

        task = await _create_ready_claimed_task(db, seeded)
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        # 创建者在 Worker 计算时暂停任务
        await pause_task(
            db, task.id, reason="需要审查",
            expected_version=task.version_no,
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
            team_id=seeded["team_id"],
        )
        await db.flush()

        result = await validate_task_active(db, seeded["agent_id"])
        assert result["ok"] is False
        assert result["reason"] == "task_paused"
        assert result["task_status"] == "paused"

    async def test_detects_cancelled_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """任务 CANCELLED 时 Worker 应停止。"""
        from src.services.task_service import terminate_task

        task = await _create_ready_claimed_task(db, seeded)
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        await terminate_task(
            db, task.id, reason="不再需要",
            expected_version=task.version_no,
            actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
            team_id=seeded["team_id"],
        )
        await db.flush()

        result = await validate_task_active(db, seeded["agent_id"])
        assert result["ok"] is False
        assert result["reason"] == "task_cancelled"

    async def test_detects_already_submitted_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """任务已被提交时 Worker 应停止。"""
        task = await _create_ready_claimed_task(db, seeded)
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        # 模拟任务已被其他进程提交
        task.status = "in_verification"
        await db.flush()

        result = await validate_task_active(db, seeded["agent_id"])
        assert result["ok"] is False
        assert result["reason"] == "task_already_submitted"

    async def test_detects_reassigned_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """任务被重新分配时 Worker 应停止。"""
        task = await _create_ready_claimed_task(db, seeded)
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        # 任务被重新分配给另一个 agent
        task.owner_id = "another-agent"
        await db.flush()

        result = await validate_task_active(db, seeded["agent_id"])
        assert result["ok"] is False
        assert result["reason"] == "task_reassigned"

    async def test_clears_stale_reference_on_deleted_task(
        self, db: AsyncSession, seeded: dict,
    ):
        """活跃任务被删除时，清除过期引用。"""
        task = await _create_ready_claimed_task(db, seeded)
        await start_task(db, seeded["agent_id"], task.id)
        await db.flush()

        # 删除任务
        await db.delete(task)
        await db.flush()

        result = await validate_task_active(db, seeded["agent_id"])
        assert result["ok"] is False
        assert result["reason"] == "task_deleted"

        # Worker 的 active_task_id 应被清除
        agent = await db.get(Worker, seeded["agent_id"])
        assert agent.active_task_id is None
