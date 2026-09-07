"""P100-B155 (PFL-263): 授权门禁 operation 维度 + cancel 接线 — 服务集成测试。

核心缺陷：`_check_no_pending_auth` 只按 (worker, task, pending) 过滤，不区分
``operation``。于是 Worker 有一个 pending ``task.assign``（handoff）请求时，
其后续的 verify/submit 等**其它** mutation 也会被这个「僵尸」请求误伤 →
PFL-263 自锁死。

本文件锁定三条语义：
1. pending ``task.assign`` 僵尸**不**阻塞 ``execute_verification``（红绿核心）
2. pending ``task.assign`` **仍**阻塞 ``assign_task``（门禁对匹配 operation 生效）
3. Worker OFFLINE→handshake 级联取消 pending 请求（层 2 接线）
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import AuthorizationOperation, TaskStatus, WorkerRuntimeStatus
from src.exceptions import ConflictError
from src.models.authorization_request import AuthorizationRequest
from src.models.member import Member
from src.models.project import Project
from src.models.project_actor_role import ProjectActorRole
from src.models.task import Task
from src.models.team import Team
from src.models.verification import Verification
from src.models.worker import Worker
from src.services.authorization_service import create_authorization_request
from src.services.task_service import (
    assign_task,
    claim_task,
    create_task,
    ready_task,
    submit_task,
)
from src.services.verification_service import execute_verification
from src.services.worker_service import worker_handshake
from src.utils.id_gen import derive_id, generate_id


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db(app) -> AsyncSession:
    """每个测试一个独立数据库会话，测试结束回滚。"""
    from src.db import async_session_factory
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def seeded(db: AsyncSession) -> dict:
    """创建 Team + Project + Member + active Worker（带 builder 角色）。"""
    team_id = generate_id("team")
    project_id = generate_id("project")
    member_id = generate_id("member")
    agent_id = generate_id("worker")

    team = Team(id=team_id, name="门禁团队", slug=f"gate-{team_id[-8:]}")
    project = Project(id=project_id, team_id=team_id, name="门禁项目", slug=f"gate-{project_id[-8:]}")
    member = Member(id=member_id, team_id=team_id, user_id="user-1", display_name="管理员", role="admin")
    agent = Worker(
        id=agent_id, team_id=team_id, name="Test Worker",
        provider="claude", provider_model="sonnet", status="active",
        registered_by=None, api_key_hash="test-hash", api_key_prefix="sk-test",
    )
    role = ProjectActorRole(
        id=generate_id("project_actor_role"),
        project_id=project_id, worker_id=agent_id, role="builder",
    )
    db.add_all([team, project, member, agent, role])
    await db.flush()
    return {
        "team_id": team_id, "project_id": project_id,
        "member_id": member_id, "agent_id": agent_id,
    }


async def _create_ready_task(db: AsyncSession, seeded: dict) -> Task:
    """创建任务并置为 READY（含 1 个 auto-created manual verification）。"""
    task = await create_task(
        db, project_id=seeded["project_id"], title="门禁测试任务",
        description="测试 operation 维度门禁", priority="p1",
        parent_task_id=None, batch_id=None, estimated_effort=None,
        tags=None, metadata=None, deadline_at=None,
        verifications=[{"type": "manual", "description": "Verify gate works correctly"}],
        actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
        team_id=seeded["team_id"],
    )
    await db.flush()
    task = await ready_task(
        db, task.id, expected_version=task.version_no,
        actor_type="human", actor_id=derive_id(seeded["member_id"], "worker"),
        team_id=seeded["team_id"],
    )
    await db.flush()
    return task


async def _mint_assign_request(db: AsyncSession, seeded: dict, task_id: str) -> None:
    """为 agent 铸造一个 pending ``task.assign`` 授权请求（handoff 僵尸）。"""
    await create_authorization_request(
        db,
        project_id=seeded["project_id"],
        worker_id=seeded["agent_id"],
        request_type="api_auth",
        operation=AuthorizationOperation.TASK_ASSIGN,
        target_resource_type="task",
        target_resource_id=task_id,
        team_id=seeded["team_id"],
        actor_type="worker",
        actor_id=seeded["agent_id"],
    )
    await db.flush()


# ═══════════════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestOperationScopedGate:
    async def test_assign_zombie_does_not_block_verify(self, db: AsyncSession, seeded: dict):
        """PFL-263 红绿核心：pending ``task.assign`` 僵尸不阻塞 verification。

        复现真实自锁死：O 为自己发 handoff → 铸造 ``task.assign`` 授权请求
        （worker_id=O），O 随后 verify 同一 task。改动前门禁只按
        (worker, task, pending) 过滤 → 命中 assign 僵尸 → 抛 PENDING_AUTHORIZATION。
        改动后加 operation=verification.verify → 僵尸被过滤 → 正常完成。
        """
        # 走 READY → claim（owner=agent A）→ submit，任务进入 IN_VERIFICATION
        task = await _create_ready_task(db, seeded)
        task = await claim_task(
            db, task.id, worker_id=seeded["agent_id"],
            worker_team_id=seeded["team_id"], expected_version=task.version_no,
        )
        await db.flush()
        task = await submit_task(
            db, task.id, summary="done",
            evidence={"output_access": {"type": "inline", "value": "test"}},
            verification_results=[], expected_version=task.version_no,
            actor_type="worker", actor_id=seeded["agent_id"],
            team_id=seeded["team_id"],
        )
        await db.flush()

        # 第二个 worker V（orchestrator 侧 verifier），且持有 pending task.assign 僵尸
        verifier_id = generate_id("worker")
        db.add(Worker(
            id=verifier_id, team_id=seeded["team_id"], name="Verifier",
            provider="claude", provider_model="sonnet", status="active",
            registered_by=None, api_key_hash="verifier-hash", api_key_prefix="sk-v",
        ))
        await db.flush()
        await create_authorization_request(
            db,
            project_id=seeded["project_id"],
            worker_id=verifier_id,
            request_type="api_auth",
            operation=AuthorizationOperation.TASK_ASSIGN,
            target_resource_type="task",
            target_resource_id=task.id,
            team_id=seeded["team_id"],
            actor_type="worker",
            actor_id=verifier_id,
        )
        await db.flush()

        ver = (await db.execute(
            select(Verification).where(Verification.task_id == task.id)
        )).scalars().one()

        # V 执行 verify：不因 task.assign 僵尸抛 PENDING_AUTHORIZATION → COMPLETED
        _, result_task = await execute_verification(
            db, verification_id=ver.id, status="passed",
            comment="ok", evidence=None, rejection_reason=None,
            expected_version=task.version_no,
            actor_type="worker", actor_id=verifier_id,
            team_id=seeded["team_id"],
        )
        assert result_task.status == TaskStatus.COMPLETED

    async def test_assign_zombie_blocks_assign(self, db: AsyncSession, seeded: dict):
        """门禁仍对匹配 operation 生效：pending ``task.assign`` 阻塞 assign_task。"""
        task = await _create_ready_task(db, seeded)

        # 僵尸：agent 有 pending task.assign 请求
        await _mint_assign_request(db, seeded, task.id)

        with pytest.raises(ConflictError, match="PENDING_AUTHORIZATION"):
            await assign_task(
                db, task.id, owner_type="member", owner_id=seeded["member_id"],
                expected_version=task.version_no,
                actor_type="worker", actor_id=seeded["agent_id"],
                team_id=seeded["team_id"],
            )


@pytest.mark.asyncio
class TestCancelWorkerRequestsWired:
    async def test_cancel_worker_requests_wired_on_restart(self, db: AsyncSession, seeded: dict):
        """层 2：Worker OFFLINE→handshake 级联取消 pending 请求。"""
        # 铸造一个 pending 请求（cancel 不区分 target，用幽灵 task id 即可）
        await _mint_assign_request(db, seeded, generate_id("task"))

        # 模拟 Worker 离线
        agent = await db.get(Worker, seeded["agent_id"])
        agent.runtime_status = WorkerRuntimeStatus.OFFLINE
        await db.flush()

        # 重新握手 → OFFLINE 分支触发 cancel_worker_requests
        await worker_handshake(
            db, seeded["agent_id"],
            worker_version="1.0.0", capabilities=[],
            supported_events=[], preferred_channel="websocket",
        )
        await db.flush()

        records = (await db.execute(
            select(AuthorizationRequest).where(
                AuthorizationRequest.worker_id == seeded["agent_id"],
            )
        )).scalars().all()
        assert records, "应有至少一条被取消的 pending 请求"
        assert all(r.status == "cancelled" for r in records)
