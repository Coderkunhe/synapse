"""P8-B1：Task 状态机 — 全面测试。

覆盖:
- 所有合法转换（8 状态 × N 条边）
- 所有非法转换尝试（每个状态一个）
- 状态机模块单元测试（无 DB）
- 服务层 pause/resume/terminate/ready（真实 DB）
- 乐观锁版本冲突检测
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import TaskStatus
from src.db import async_session_factory
from src.exceptions import ConflictError, InvalidStateTransition
from src.models.worker import Worker
from src.models.project import Project
from src.models.team import Team
from src.task_state_machine import (
    ALLOWED_TRANSITIONS,
    get_event_type,
    is_active,
    is_terminal,
    validate_transition,
)
from src.utils.id_gen import generate_id


# ═══════════════════════════════════════════════════════════════════
# 单元测试：状态机模块（无 DB）
# ═══════════════════════════════════════════════════════════════════


class TestTransitionWhitelist:
    """验证转换白名单覆盖全部 8 个状态。"""

    ALL_STATES = frozenset(TaskStatus)
    EXPECTED_TERMINAL = frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED})

    def test_all_statuses_have_transition_entries(self):
        """每个 TaskStatus 必须在 ALLOWED_TRANSITIONS 中有条目。"""
        for status in self.ALL_STATES:
            assert status in ALLOWED_TRANSITIONS, f"Missing transition entry for {status}"

    def test_terminal_states_have_no_outgoing(self):
        """COMPLETED 和 CANCELLED 的目标集合必须为空。"""
        for status in self.EXPECTED_TERMINAL:
            assert ALLOWED_TRANSITIONS[status] == frozenset(), (
                f"{status} should be terminal but has outgoing: {ALLOWED_TRANSITIONS[status]}"
            )

    def test_active_states_have_outgoing(self):
        """每个非终态至少有一个出边转换。"""
        for status in self.ALL_STATES - self.EXPECTED_TERMINAL:
            assert len(ALLOWED_TRANSITIONS[status]) > 0, (
                f"{status} should have outgoing transitions"
            )

    def test_paused_transitions(self):
        """PAUSED 可转到 IN_PROGRESS（恢复）和 CANCELLED（终止）。"""
        targets = ALLOWED_TRANSITIONS[TaskStatus.PAUSED]
        assert TaskStatus.IN_PROGRESS in targets
        assert TaskStatus.CANCELLED in targets

    def test_rejected_transitions(self):
        """REJECTED 只能转到 IN_PROGRESS（返工）。"""
        targets = ALLOWED_TRANSITIONS[TaskStatus.REJECTED]
        assert targets == frozenset({TaskStatus.IN_PROGRESS})

    def test_in_progress_transitions_includes_paused(self):
        """IN_PROGRESS → PAUSED 必须在白名单中。"""
        targets = ALLOWED_TRANSITIONS[TaskStatus.IN_PROGRESS]
        assert TaskStatus.PAUSED in targets


class TestValidateTransition:
    """validate_transition() 对非法转换抛异常，合法转换通过。"""

    def test_all_valid_transitions_pass(self):
        """白名单中的每个转换必须验证通过。"""
        for from_status, targets in ALLOWED_TRANSITIONS.items():
            for to_status in targets:
                # 不应抛异常
                validate_transition(from_status, to_status)

    def test_invalid_transition_raises(self):
        """非法转换必须抛出 InvalidStateTransition。"""
        with pytest.raises(InvalidStateTransition) as exc:
            validate_transition(TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS)
        assert "COMPLETED" in str(exc.value.message).upper() or "completed" in str(exc.value.message)

    def test_rejected_to_completed_invalid(self):
        """REJECTED → COMPLETED 非法（必须经过 IN_PROGRESS → IN_VERIFICATION）。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(TaskStatus.REJECTED, TaskStatus.COMPLETED)

    def test_paused_to_completed_invalid(self):
        """PAUSED → COMPLETED 非法（必须先恢复）。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(TaskStatus.PAUSED, TaskStatus.COMPLETED)

    def test_in_progress_to_completed_invalid(self):
        """IN_PROGRESS → COMPLETED 非法（必须经过 IN_VERIFICATION）。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED)

    def test_in_verification_to_paused_invalid(self):
        """IN_VERIFICATION → PAUSED 非法。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(TaskStatus.IN_VERIFICATION, TaskStatus.PAUSED)

    def test_ready_to_completed_invalid(self):
        """READY → COMPLETED 非法。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(TaskStatus.READY, TaskStatus.COMPLETED)


class TestEventTypeMapping:
    """get_event_type() 为每个转换返回正确的事件类型。"""

    def test_backlog_to_ready(self):
        assert get_event_type(TaskStatus.BACKLOG, TaskStatus.READY) == "task.readied"

    def test_ready_to_in_progress(self):
        assert get_event_type(TaskStatus.READY, TaskStatus.IN_PROGRESS) == "task.claimed"

    def test_in_progress_to_paused(self):
        assert get_event_type(TaskStatus.IN_PROGRESS, TaskStatus.PAUSED) == "task.paused"

    def test_paused_to_in_progress(self):
        assert get_event_type(TaskStatus.PAUSED, TaskStatus.IN_PROGRESS) == "task.resumed"

    def test_in_progress_to_in_verification(self):
        assert get_event_type(TaskStatus.IN_PROGRESS, TaskStatus.IN_VERIFICATION) == "task.submitted"

    def test_in_verification_to_completed(self):
        assert get_event_type(TaskStatus.IN_VERIFICATION, TaskStatus.COMPLETED) == "task.completed"

    def test_in_verification_to_rejected(self):
        assert get_event_type(TaskStatus.IN_VERIFICATION, TaskStatus.REJECTED) == "task.rejected"

    def test_rejected_to_in_progress(self):
        assert get_event_type(TaskStatus.REJECTED, TaskStatus.IN_PROGRESS) == "task.claimed"

    def test_in_verification_to_in_progress(self):
        """P11-B88: IN_VERIFICATION → IN_PROGRESS = task.verification_timeout_reverted。"""
        assert get_event_type(TaskStatus.IN_VERIFICATION, TaskStatus.IN_PROGRESS) == "task.verification_timeout_reverted"

    def test_any_to_cancelled(self):
        """所有可取消路径均映射到 task.cancelled。"""
        for from_status in [TaskStatus.BACKLOG, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.PAUSED]:
            assert get_event_type(from_status, TaskStatus.CANCELLED) == "task.cancelled"


class TestTerminalAndActive:
    """is_terminal() 和 is_active() 辅助函数。"""

    def test_completed_is_terminal(self):
        assert is_terminal(TaskStatus.COMPLETED) is True

    def test_cancelled_is_terminal(self):
        assert is_terminal(TaskStatus.CANCELLED) is True

    def test_rejected_is_not_terminal(self):
        assert is_terminal(TaskStatus.REJECTED) is False

    def test_paused_is_not_terminal(self):
        assert is_terminal(TaskStatus.PAUSED) is False

    def test_backlog_is_not_active(self):
        assert is_active(TaskStatus.BACKLOG) is False

    def test_ready_is_active(self):
        assert is_active(TaskStatus.READY) is True

    def test_completed_is_not_active(self):
        assert is_active(TaskStatus.COMPLETED) is False


# ═══════════════════════════════════════════════════════════════════
# 集成测试夹具
# ═══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db(app) -> AsyncSession:
    """每个测试独立的 DB session — 依赖 app 夹具以确保表已创建。

    使用 session.begin() 作为事务边界。需要服务端默认值
    （如 version_no）的服务函数必须在创建实体后调用 ``await db.flush()``。
    """
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def seeded_project(db: AsyncSession) -> Project:
    """在测试 DB 中创建 Team + Project + Worker。"""
    from src.models.member import Member

    team_id = generate_id("team")
    project_id = generate_id("project")
    agent_id = generate_id("worker")
    member_id = generate_id("member")

    team = Team(id=team_id, name="Test Team", slug=f"test-{team_id[-8:]}")
    project = Project(id=project_id, team_id=team_id, name="Test Project", slug=f"proj-{project_id[-8:]}")
    member = Member(id=member_id, team_id=team_id, user_id="user-1", display_name="Admin", role="admin")
    agent = Worker(
        id=agent_id, team_id=team_id, name="Test Worker",
        provider="claude", provider_model="sonnet", status="active",
        registered_by=None, api_key_hash="test-hash", api_key_prefix="sk-test",
    )

    db.add_all([team, project, member, agent])
    await db.flush()
    # 附加 agent_id 供测试辅助函数使用
    project._test_agent_id = agent_id
    return project


# ═══════════════════════════════════════════════════════════════════
# 集成测试：服务函数（带 DB）
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestReadyTask:
    """backlog → ready 转换（通过服务层）。"""

    async def test_ready_task_success(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import create_task, ready_task

        task = await create_task(
            db, project_id=seeded_project.id, title="Test Ready",
            description="Has description", priority="p1",
            parent_task_id=None, batch_id=None, estimated_effort=None,
            tags=None, metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Check verification works correctly"}],
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        await db.flush()  # 解析服务端默认值（version_no）
        assert task.status == "backlog"

        result = await ready_task(
            db, task.id, expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        assert result.status == "ready"

    async def test_ready_task_no_description_fails(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import create_task, ready_task

        task = await create_task(
            db, project_id=seeded_project.id, title="No Desc",
            description=None, priority="p1",
            parent_task_id=None, batch_id=None, estimated_effort=None,
            tags=None, metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Check verification works correctly"}],
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        with pytest.raises(ConflictError, match="TASK_NOT_READY"):
            await ready_task(
                db, task.id, expected_version=task.version_no,
                actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
            )

    async def test_ready_task_version_conflict(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import create_task, ready_task

        task = await create_task(
            db, project_id=seeded_project.id, title="VC",
            description="Has desc", priority="p1",
            parent_task_id=None, batch_id=None, estimated_effort=None,
            tags=None, metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Check verification works correctly"}],
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        with pytest.raises(ConflictError, match="VERSION_CONFLICT"):
            await ready_task(
                db, task.id, expected_version=999,
                actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
            )

    async def test_ready_task_invalid_transition(self, db: AsyncSession, seeded_project: Project):
        """从终态（COMPLETED）执行 ready_task 应失败。

        注意：IN_PROGRESS → READY 现在是合法的（P8-B3 lease 过期），
        因此原来使用 IN_PROGRESS 任务的测试已不再适用。
        """
        from src.services.task_service import ready_task
        task = await _create_completed_task(db, seeded_project)
        assert task.status == "completed"
        with pytest.raises(InvalidStateTransition):
            await ready_task(
                db, task.id, expected_version=task.version_no,
                actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
            )


@pytest.mark.asyncio
class TestPauseResumeTask:
    """IN_PROGRESS → PAUSED → IN_PROGRESS 循环。"""

    async def test_pause_task_success(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import pause_task

        task = await _create_ready_claimed_task(db, seeded_project)
        result = await pause_task(
            db, task.id, reason="Need to investigate",
            expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        assert result.status == "paused"
        assert result.paused_at is not None
        assert result.paused_by == "user-1"
        assert result.pause_reason == "Need to investigate"

    async def test_resume_task_success(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import pause_task, resume_task

        task = await _create_ready_claimed_task(db, seeded_project)
        paused = await pause_task(
            db, task.id, reason="Test", expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        resumed = await resume_task(
            db, paused.id, expected_version=paused.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        assert resumed.status == "in_progress"
        assert resumed.paused_at is None
        assert resumed.paused_by is None
        assert resumed.pause_reason is None

    async def test_pause_from_ready_fails(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import create_task, pause_task, ready_task

        task = await create_task(
            db, project_id=seeded_project.id, title="Ready",
            description="Has desc", priority="p1",
            parent_task_id=None, batch_id=None, estimated_effort=None,
            tags=None, metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Check verification works correctly"}],
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        task = await ready_task(
            db, task.id, expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        with pytest.raises(InvalidStateTransition):
            await pause_task(
                db, task.id, reason="nope", expected_version=task.version_no,
                actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
            )

    async def test_pause_version_conflict(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import pause_task

        task = await _create_ready_claimed_task(db, seeded_project)
        with pytest.raises(ConflictError, match="VERSION_CONFLICT"):
            await pause_task(
                db, task.id, reason="Stale", expected_version=999,
                actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
            )


@pytest.mark.asyncio
class TestTerminateTask:
    """从各种状态终止任务 → CANCELLED。"""

    async def test_terminate_from_in_progress(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import terminate_task

        task = await _create_ready_claimed_task(db, seeded_project)
        result = await terminate_task(
            db, task.id, reason="No longer needed",
            expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        assert result.status == "cancelled"
        assert result.owner_id is None
        assert result.owner_type is None

    async def test_terminate_from_paused(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import pause_task, terminate_task

        task = await _create_ready_claimed_task(db, seeded_project)
        paused = await pause_task(
            db, task.id, reason="Test", expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        result = await terminate_task(
            db, paused.id, reason="Obsolete", expected_version=paused.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        assert result.status == "cancelled"

    async def test_terminate_from_ready(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import create_task, ready_task, terminate_task

        task = await create_task(
            db, project_id=seeded_project.id, title="Term",
            description="Will be cancelled", priority="p1",
            parent_task_id=None, batch_id=None, estimated_effort=None,
            tags=None, metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Check verification works correctly"}],
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        task = await ready_task(
            db, task.id, expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        result = await terminate_task(
            db, task.id, reason="Not needed", expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
        )
        assert result.status == "cancelled"

    async def test_terminate_completed_fails(self, db: AsyncSession, seeded_project: Project):
        from src.services.task_service import terminate_task

        task = await _create_completed_task(db, seeded_project)
        with pytest.raises(InvalidStateTransition):
            await terminate_task(
                db, task.id, reason="Too late", expected_version=task.version_no,
                actor_type="human", actor_id="user-1", team_id=seeded_project.team_id,
            )


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════


async def _create_ready_claimed_task(db: AsyncSession, project: Project):
    """创建任务、设为 READY、claim → 返回 IN_PROGRESS 状态的任务。"""
    from src.services.task_service import claim_task, create_task, ready_task

    task = await create_task(
        db, project_id=project.id, title="Test Task",
        description="Test description", priority="p1",
        parent_task_id=None, batch_id=None, estimated_effort=None,
        tags=None, metadata=None, deadline_at=None,
        verifications=[{"type": "manual", "description": "Verify output"}],
        actor_type="human", actor_id="user-1", team_id=project.team_id,
    )
    await db.flush()  # 解析服务端默认值（version_no 等）
    task = await ready_task(
        db, task.id, expected_version=task.version_no,
        actor_type="human", actor_id="user-1", team_id=project.team_id,
    )
    await db.flush()
    agent_id = getattr(project, "_test_agent_id", "agent-1")
    task = await claim_task(
        db, task.id, worker_id=agent_id,
        worker_team_id=project.team_id, expected_version=task.version_no,
    )
    await db.flush()
    return task


async def _create_completed_task(db: AsyncSession, project: Project):
    """创建任务并走完流程到 COMPLETED。"""
    from src.services.task_service import submit_task
    from src.services.verification_service import execute_verification
    from src.models.verification import Verification
    from sqlalchemy import select as sa_select

    agent_id = getattr(project, "_test_agent_id", "agent-1")
    task = await _create_ready_claimed_task(db, project)
    await db.flush()
    task = await submit_task(
        db, task.id, summary="Done", evidence={"output_access": {"type": "inline", "value": "test"}},
        verification_results=[], expected_version=task.version_no,
        actor_type="worker", actor_id=agent_id, team_id=project.team_id,
    )
    await db.flush()
    result = await db.execute(
        sa_select(Verification).where(Verification.task_id == task.id)
    )
    for v in result.scalars().all():
        verification, task = await execute_verification(
            db, verification_id=v.id, status="passed",
            comment="LGTM", evidence=None, rejection_reason=None,
            expected_version=task.version_no,
            actor_type="human", actor_id="user-1", team_id=project.team_id,
        )
        await db.flush()
    return task
