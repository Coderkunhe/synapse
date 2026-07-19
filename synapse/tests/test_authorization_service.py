"""P10-B21: AuthorizationRequest Service 层测试。

覆盖:
- create: 字段组校验 · 流控上限 · 正常创建
- respond: pending→approved/denied · 非 pending 拒绝
- heartbeat: 正常续期 · 非 pending 拒绝
- expire: 批量过期 · 空结果
- cancel: Worker 级联取消 · 空结果
- get_pending_count: 计数准确性
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import pytest_asyncio

from src.constants import MAX_PENDING_AUTH_REQUESTS, ActorType
from src.db import async_session_factory
from src.exceptions import (
    ConflictError,
    ForbiddenError,
    InvalidStateTransition,
    NotFoundError,
)
from src.models.authorization_request import AuthorizationRequest
from src.models.worker import Worker
from src.services.authorization_service import (
    cancel_worker_requests,
    create_authorization_request,
    expire_stale_requests,
    get_pending_count,
    get_request,
    heartbeat,
    respond_to_request,
)
from src.utils.id_gen import generate_id


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db_session():
    """每个测试一个独立数据库会话，测试结束回滚."""
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def actor_info(seed):
    """从 seed 数据中提取事件元信息。"""
    return {
        "team_id": seed.team_id,
        "actor_type": ActorType.WORKER,
        "actor_id": seed.worker_id,
    }


@pytest.fixture
async def test_worker(db_session, seed):
    """创建一个测试用的 Worker，返回其 ID。"""
    worker = Worker(
        id=generate_id("worker"),
        name="Test Agent",
        team_id=seed.team_id,
        actor_type="agent",
        status="active",
        api_key_hash="",
    )
    db_session.add(worker)
    await db_session.commit()
    return worker.id


@pytest.fixture
async def test_project(db_session, seed):
    """创建一个测试用的 Project。"""
    from src.models.project import Project
    project = Project(
        id=generate_id("project"),
        name="Test Project",
        slug=f"test-project-{generate_id('project')[-8:]}",
        team_id=seed.team_id,
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


# ═══════════════════════════════════════════════════════════════════
# create_authorization_request
# ═══════════════════════════════════════════════════════════════════


class TestCreateAuthRequest:
    """创建授权请求 — 校验 + 流控."""

    async def test_create_api_auth_success(
        self, db_session, test_project, test_worker, actor_info
    ):
        """创建 api_auth 类型请求成功."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="task.assign",
            target_resource_type="task",
            target_resource_id="tsk_001",
            **actor_info,
        )
        await db_session.commit()

        assert record.id.startswith("areq_")
        assert record.request_type == "api_auth"
        assert record.operation == "task.assign"
        assert record.status == "pending"
        assert record.expires_at > datetime.now(timezone.utc)
        assert record.last_heartbeat_at is not None

    async def test_create_interactive_prompt_success(
        self, db_session, test_project, test_worker, actor_info
    ):
        """创建 interactive_prompt 类型请求成功."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="interactive_prompt",
            prompt_type="confirm",
            prompt_message="是否批准此操作？",
            prompt_choices=["批准", "拒绝"],
            **actor_info,
        )
        await db_session.commit()

        assert record.request_type == "interactive_prompt"
        assert record.prompt_type == "confirm"
        assert record.prompt_message == "是否批准此操作？"
        assert record.prompt_choices_json is not None
        assert "批准" in record.prompt_choices_json

    async def test_api_auth_missing_operation(
        self, db_session, test_project, test_worker, actor_info
    ):
        """api_auth 缺 operation → ForbiddenError."""
        with pytest.raises(ForbiddenError) as exc_info:
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                **actor_info,
            )
        assert "operation" in exc_info.value.message

    async def test_interactive_prompt_missing_prompt_type(
        self, db_session, test_project, test_worker, actor_info
    ):
        """interactive_prompt 缺 prompt_type → ForbiddenError."""
        with pytest.raises(ForbiddenError) as exc_info:
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="interactive_prompt",
                prompt_message="some message",
                **actor_info,
            )
        assert "prompt_type" in exc_info.value.message

    async def test_interactive_prompt_missing_prompt_message(
        self, db_session, test_project, test_worker, actor_info
    ):
        """interactive_prompt 缺 prompt_message → ForbiddenError."""
        with pytest.raises(ForbiddenError) as exc_info:
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="interactive_prompt",
                prompt_type="confirm",
                **actor_info,
            )
        assert "prompt_message" in exc_info.value.message

    async def test_flow_control_max_pending(
        self, db_session, test_project, test_worker, actor_info
    ):
        """超过流控上限 → ConflictError."""
        # 创建 MAX_PENDING 个 pending 请求
        for i in range(MAX_PENDING_AUTH_REQUESTS):
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                operation=f"task.assign.{i}",
                **actor_info,
            )
        await db_session.commit()

        # 第 6 个应该被拒绝
        with pytest.raises(ConflictError) as exc_info:
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                operation="task.assign.overflow",
                **actor_info,
            )
        assert "TOO_MANY_PENDING_REQUESTS" in exc_info.value.code

    async def test_flow_control_allows_after_resolved(
        self, db_session, test_project, test_worker, actor_info
    ):
        """一个被批准后，可以创建新的."""
        # 创建 MAX_PENDING 个
        for i in range(MAX_PENDING_AUTH_REQUESTS):
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                operation=f"task.{i}",
                **actor_info,
            )
        await db_session.commit()

        # 批准第一个
        first = await db_session.execute(
            select(AuthorizationRequest)
            .where(AuthorizationRequest.worker_id == test_worker)
            .limit(1)
        )
        first_req = first.scalar_one()
        await respond_to_request(
            db_session,
            request_id=first_req.id,
            responder_worker_id=actor_info["actor_id"],
            status="approved",
            **actor_info,
        )
        await db_session.commit()

        # 现在可以创建新的
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="task.new",
            **actor_info,
        )
        await db_session.commit()
        assert record.status == "pending"

    async def test_custom_ttl(self, db_session, test_project, test_worker, actor_info):
        """自定义 TTL 被正确应用."""
        now = datetime.now(timezone.utc)
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="test.ttl",
            ttl_seconds=600,  # 10 分钟
            **actor_info,
        )
        await db_session.commit()

        delta = record.expires_at - now
        assert 590 <= delta.total_seconds() <= 610  # 允许少量偏差


# ═══════════════════════════════════════════════════════════════════
# respond_to_request
# ═══════════════════════════════════════════════════════════════════


class TestRespondToRequest:
    """响应授权请求 — approve/deny."""

    async def test_approve_pending_request(
        self, db_session, test_project, test_worker, actor_info
    ):
        """批准 pending 请求."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="task.approve",
            **actor_info,
        )
        await db_session.commit()

        updated = await respond_to_request(
            db_session,
            request_id=record.id,
            responder_worker_id=actor_info["actor_id"],
            status="approved",
            response_note="同意执行",
            **actor_info,
        )
        await db_session.commit()

        assert updated.status == "approved"
        assert updated.responded_by_worker_id == actor_info["actor_id"]
        assert updated.responded_at is not None
        assert updated.response_note == "同意执行"

    async def test_deny_pending_request(
        self, db_session, test_project, test_worker, actor_info
    ):
        """拒绝 pending 请求."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="task.deny",
            **actor_info,
        )
        await db_session.commit()

        updated = await respond_to_request(
            db_session,
            request_id=record.id,
            responder_worker_id=actor_info["actor_id"],
            status="denied",
            response_note="权限不足",
            **actor_info,
        )
        await db_session.commit()

        assert updated.status == "denied"
        assert updated.response_note == "权限不足"

    async def test_cannot_respond_non_pending(
        self, db_session, test_project, test_worker, actor_info
    ):
        """非 pending 请求不能响应."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="test.done",
            **actor_info,
        )
        await db_session.commit()

        # 先批准
        await respond_to_request(
            db_session,
            request_id=record.id,
            responder_worker_id=actor_info["actor_id"],
            status="approved",
            **actor_info,
        )
        await db_session.commit()

        # 再次响应 → 报错
        with pytest.raises(InvalidStateTransition):
            await respond_to_request(
                db_session,
                request_id=record.id,
                responder_worker_id=actor_info["actor_id"],
                status="denied",
                **actor_info,
            )

    async def test_respond_nonexistent_request(self, db_session, actor_info):
        """响应不存在的请求 → NotFoundError."""
        with pytest.raises(NotFoundError):
            await respond_to_request(
                db_session,
                request_id="areq_nonexistent",
                responder_worker_id=actor_info["actor_id"],
                status="approved",
                **actor_info,
            )


# ═══════════════════════════════════════════════════════════════════
# heartbeat
# ═══════════════════════════════════════════════════════════════════


class TestHeartbeat:
    """心跳续期."""

    async def test_heartbeat_updates_timestamp(
        self, db_session, test_project, test_worker, actor_info
    ):
        """心跳更新 last_heartbeat_at."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="test.heartbeat",
            **actor_info,
        )
        await db_session.commit()

        original_heartbeat = record.last_heartbeat_at

        # 小延迟确保时间戳不同
        import asyncio
        await asyncio.sleep(0.1)

        updated = await heartbeat(db_session, record.id)
        await db_session.commit()

        assert updated.last_heartbeat_at > original_heartbeat

    async def test_heartbeat_non_pending_fails(
        self, db_session, test_project, test_worker, actor_info
    ):
        """非 pending 请求心跳报错."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="test.hb_done",
            **actor_info,
        )
        await db_session.commit()

        # 先批准
        await respond_to_request(
            db_session,
            request_id=record.id,
            responder_worker_id=actor_info["actor_id"],
            status="approved",
            **actor_info,
        )
        await db_session.commit()

        with pytest.raises(InvalidStateTransition):
            await heartbeat(db_session, record.id)

    async def test_heartbeat_nonexistent(self, db_session):
        """不存在请求心跳 → NotFoundError."""
        with pytest.raises(NotFoundError):
            await heartbeat(db_session, "areq_nonexistent")


# ═══════════════════════════════════════════════════════════════════
# expire_stale_requests
# ═══════════════════════════════════════════════════════════════════


class TestExpireStaleRequests:
    """批量过期."""

    async def test_expire_stale_requests(
        self, db_session, test_project, test_worker, actor_info
    ):
        """过期请求被标记为 expired."""
        # 创建一个已过期的请求（直接 SQL 设置）
        now = datetime.now(timezone.utc)
        past = now - timedelta(seconds=60)
        from src.models.authorization_request import AuthorizationRequest as AR

        record = AR(
            id=generate_id("authorization_request"),
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="test.expire",
            status="pending",
            expires_at=past,
            last_heartbeat_at=past,
        )
        db_session.add(record)
        await db_session.commit()

        count = await expire_stale_requests(db_session)
        await db_session.commit()

        assert count == 1

        # 重新加载验证
        refreshed = await get_request(db_session, record.id)
        assert refreshed.status == "expired"

    async def test_expire_only_pending(
        self, db_session, test_project, test_worker, actor_info
    ):
        """只过期 pending 状态的请求."""
        now = datetime.now(timezone.utc)
        past = now - timedelta(seconds=60)

        # 已批准的过期时间请求不应被过期
        from src.models.authorization_request import AuthorizationRequest as AR
        approved = AR(
            id=generate_id("authorization_request"),
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="test.already_approved",
            status="approved",
            expires_at=past,
            last_heartbeat_at=past,
        )
        db_session.add(approved)
        await db_session.commit()

        count = await expire_stale_requests(db_session)
        await db_session.commit()

        assert count == 0
        refreshed = await get_request(db_session, approved.id)
        assert refreshed.status == "approved"

    async def test_expire_no_stale_returns_zero(self, db_session):
        """没有过期请求时返回 0."""
        count = await expire_stale_requests(db_session)
        assert count == 0


# ═══════════════════════════════════════════════════════════════════
# cancel_worker_requests
# ═══════════════════════════════════════════════════════════════════


class TestCancelWorkerRequests:
    """Worker 重启级联失效."""

    async def test_cancel_all_pending_for_worker(
        self, db_session, test_project, test_worker, actor_info
    ):
        """取消 Worker 的所有 pending 请求."""
        # 创建 3 个 pending 请求
        for i in range(3):
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                operation=f"test.cancel.{i}",
                **actor_info,
            )
        await db_session.commit()

        count = await cancel_worker_requests(
            db_session,
            worker_id=test_worker,
        )
        await db_session.commit()

        assert count == 3

        # 验证全都 cancelled
        result = await db_session.execute(
            select(AuthorizationRequest).where(
                AuthorizationRequest.worker_id == test_worker,
            )
        )
        for record in result.scalars().all():
            assert record.status == "cancelled"

    async def test_cancel_only_target_worker(
        self, db_session, test_project, test_worker, actor_info
    ):
        """只取消目标 Worker 的请求."""
        # Worker A: 创建 2 个
        for i in range(2):
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                operation=f"worker_a.{i}",
                **actor_info,
            )
        await db_session.commit()

        # Worker B: 创建 2 个
        worker_b = Worker(
            id=generate_id("worker"),
            name="Worker B",
            team_id=actor_info["team_id"],
            actor_type="agent",
            status="active",
            api_key_hash="",
        )
        db_session.add(worker_b)
        await db_session.commit()

        for i in range(2):
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=worker_b.id,
                request_type="api_auth",
                operation=f"worker_b.{i}",
                **actor_info,
            )
        await db_session.commit()

        # 只取消 Worker A
        count = await cancel_worker_requests(
            db_session,
            worker_id=test_worker,
        )
        await db_session.commit()

        assert count == 2

        # Worker A 的应该 cancelled
        result_a = await db_session.execute(
            select(AuthorizationRequest).where(
                AuthorizationRequest.worker_id == test_worker,
            )
        )
        for record in result_a.scalars().all():
            assert record.status == "cancelled"

        # Worker B 的应该仍是 pending
        result_b = await db_session.execute(
            select(AuthorizationRequest).where(
                AuthorizationRequest.worker_id == worker_b.id,
            )
        )
        for record in result_b.scalars().all():
            assert record.status == "pending"

    async def test_cancel_no_pending_returns_zero(self, db_session):
        """没有 pending 请求时返回 0."""
        count = await cancel_worker_requests(
            db_session,
            worker_id=generate_id("worker"),
        )
        assert count == 0


# ═══════════════════════════════════════════════════════════════════
# get_pending_count / get_request
# ═══════════════════════════════════════════════════════════════════


class TestQueryHelpers:
    """查询辅助函数."""

    async def test_get_pending_count_zero(self, db_session, test_worker):
        """新 Worker 无 pending 请求."""
        count = await get_pending_count(db_session, test_worker)
        assert count == 0

    async def test_get_pending_count_with_requests(
        self, db_session, test_project, test_worker, actor_info
    ):
        """有 pending 请求时计数正确."""
        for i in range(3):
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                operation=f"test.count.{i}",
                **actor_info,
            )
        await db_session.commit()

        count = await get_pending_count(db_session, test_worker)
        assert count == 3

    async def test_get_pending_count_excludes_non_pending(
        self, db_session, test_project, test_worker, actor_info
    ):
        """非 pending 的不计入."""
        # 创建 2 个 pending
        for i in range(2):
            await create_authorization_request(
                db_session,
                project_id=test_project,
                worker_id=test_worker,
                request_type="api_auth",
                operation=f"test.active.{i}",
                **actor_info,
            )
        await db_session.commit()

        # 批准一个
        result = await db_session.execute(
            select(AuthorizationRequest)
            .where(AuthorizationRequest.worker_id == test_worker)
            .limit(1)
        )
        req = result.scalar_one()
        await respond_to_request(
            db_session,
            request_id=req.id,
            responder_worker_id=actor_info["actor_id"],
            status="approved",
            **actor_info,
        )
        await db_session.commit()

        count = await get_pending_count(db_session, test_worker)
        assert count == 1

    async def test_get_request_success(self, db_session, test_project, test_worker, actor_info):
        """正常获取请求."""
        record = await create_authorization_request(
            db_session,
            project_id=test_project,
            worker_id=test_worker,
            request_type="api_auth",
            operation="test.get",
            **actor_info,
        )
        await db_session.commit()

        fetched = await get_request(db_session, record.id)
        assert fetched.id == record.id
        assert fetched.operation == "test.get"

    async def test_get_request_not_found(self, db_session):
        """不存在的请求 → NotFoundError."""
        with pytest.raises(NotFoundError):
            await get_request(db_session, "areq_nonexistent")
