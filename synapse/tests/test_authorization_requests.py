"""P10-B22: AuthorizationRequest API 端点 E2E 测试。

覆盖:
- POST   /projects/{pid}/authorization-requests  创建 · 校验 · 权限
- GET    /projects/{pid}/authorization-requests  列表 · 筛选 · 分页
- PATCH  /authorization-requests/{id}/respond    审批 · 状态机 · 权限
- PATCH  /authorization-requests/{id}/heartbeat  续期 · 所有权 · 权限
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.constants import MAX_PENDING_AUTH_REQUESTS
from src.db import async_session_factory
from src.models.authorization_request import AuthorizationRequest
from src.models.project_actor_role import ProjectActorRole
from src.models.worker import Worker
from src.utils.id_gen import generate_id
from tests.conftest import auth_header


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
async def test_project(seed):
    """创建测试 Project 并授予 admin role。"""
    from src.models.project import Project

    project_id = generate_id("project")
    async with async_session_factory() as db:
        project = Project(
            id=project_id,
            name="Test Auth Project",
            slug=f"auth-project-{project_id[-8:]}",
            team_id=seed.team_id,
        )
        db.add(project)
        await db.commit()

        # 给 seed actor 分配 project admin 角色
        role = ProjectActorRole(
            id=generate_id("project_actor_role"),
            project_id=project_id,
            worker_id=seed.worker_id,
            role="admin",
        )
        db.add(role)
        await db.commit()

    return project_id


@pytest.fixture
async def test_worker(seed):
    """创建测试 Agent Worker（含 git.push capability）。"""
    from src.models.capability import Capability
    worker_id = generate_id("worker")
    async with async_session_factory() as db:
        worker = Worker(
            id=worker_id,
            name="Test Agent",
            team_id=seed.team_id,
            actor_type="agent",
            status="active",
            api_key_hash="",
        )
        db.add(worker)
        # P11-B95: declare capability so capability_exec tests work
        cap = Capability(
            id=generate_id("capability"),
            worker_id=worker_id,
            name="git.push",
        )
        db.add(cap)
        await db.commit()
    return worker_id


# ═══════════════════════════════════════════════════════════════════
# POST /projects/{project_id}/authorization-requests
# ═══════════════════════════════════════════════════════════════════


class TestCreateAuthRequest:
    """创建授权请求 API."""

    async def test_create_api_auth(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """POST 创建 api_auth 请求."""
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "task.assign",
                "target_resource_type": "task",
                "target_resource_id": "tsk_001",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["request_type"] == "api_auth"
        assert data["status"] == "pending"
        assert data["worker_id"] == test_worker
        assert data["project_id"] == test_project

    async def test_create_interactive_prompt(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """POST 创建 interactive_prompt 请求."""
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "interactive_prompt",
                "prompt_type": "confirm",
                "prompt_message": "是否批准？",
                "prompt_choices": ["批准", "拒绝"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["request_type"] == "interactive_prompt"
        assert data["prompt_choices"] == ["批准", "拒绝"]

    async def test_create_without_project_role(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """无 project role → 403."""
        # 删除 seed actor 的 project role
        async with async_session_factory() as db:
            from sqlalchemy import delete
            await db.execute(
                delete(ProjectActorRole).where(
                    ProjectActorRole.project_id == test_project,
                    ProjectActorRole.worker_id == seed.worker_id,
                )
            )
            await db.commit()

        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.no_role",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 403

    async def test_create_project_id_mismatch(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """Body project_id 与 URL 不一致 → 403."""
        other_project = generate_id("project")
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": other_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.mismatch",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 403

    async def test_create_missing_operation(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """api_auth 缺 operation → 403（service 层校验）."""
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 403
        assert "operation" in resp.json()["error"]["message"]

    async def test_create_flow_control(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """超过流控上限 → 409."""
        # 创建 MAX_PENDING 个
        for i in range(MAX_PENDING_AUTH_REQUESTS):
            resp = await client.post(
                f"/v1/projects/{test_project}/authorization-requests",
                json={
                    "project_id": test_project,
                    "worker_id": test_worker,
                    "request_type": "api_auth",
                    "operation": f"test.flow.{i}",
                },
                headers=auth_header(seed.token),
            )
            assert resp.status_code == 201, f"Request {i} failed: {resp.text}"

        # 第 6 个应该 409
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.overflow",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 409
        assert "TOO_MANY_PENDING_REQUESTS" in resp.json()["error"]["code"]

    # ── P11-B47: Worker 自请求 capability_exec ──────────────────

    async def test_create_capability_exec_self_request(
        self, client: AsyncClient, seed, test_project
    ):
        """Worker 通过 API key 创建自己的 capability_exec 请求 → 201。

        P11-B47: capability_exec + worker_id==actor.actor_id → 旁路 admin/lead role 检查。
        这是 Capability MVP 的核心权限模型——Worker 自请求执行能力，不需要人类管理员代为创建。
        """
        import hashlib
        import secrets

        from src.constants import WorkerActorType, WorkerStatus
        from src.models.capability import Capability
        from src.models.worker import Worker
        from src.utils.id_gen import generate_id

        # 创建带 API key 的 Worker
        worker_id = generate_id("worker")
        raw_key = f"sk-syn-{secrets.token_hex(32)}.{worker_id.replace('wor_', '')[-8:]}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        async with async_session_factory() as db:
            worker = Worker(
                id=worker_id,
                name="B47 Test Agent",
                team_id=seed.team_id,
                actor_type=WorkerActorType.AGENT,
                status=WorkerStatus.ACTIVE,
                api_key_hash=key_hash,
            )
            db.add(worker)
            # P11-B95: Worker must declare the capability before requesting capability_exec
            cap = Capability(
                id=generate_id("capability"),
                worker_id=worker_id,
                name="git.push",
            )
            db.add(cap)
            await db.commit()

        # Worker 用 API key 为自己创建 capability_exec 请求
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": worker_id,
                "request_type": "capability_exec",
                "capability_id": "git_push_main",
                "operation": "git.push",
                "prompt_message": "P11-B47 狗粮验证完成",
            },
            headers=auth_header(raw_key),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["request_type"] == "capability_exec"
        assert data["worker_id"] == worker_id
        assert data["capability_id"] == "git_push_main"
        assert data["status"] == "pending"

    async def test_create_capability_exec_for_other_worker_forbidden(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """Worker 为其他 Worker 创建 capability_exec → 403。

        P11-B47: 只有 worker_id==actor.actor_id 才旁路 role 检查。
        为其他 Worker 创建 capability_exec 仍需 admin/lead。
        """
        import hashlib
        import secrets

        from src.constants import WorkerActorType, WorkerStatus
        from src.models.worker import Worker
        from src.utils.id_gen import generate_id

        worker_id = generate_id("worker")
        raw_key = f"sk-syn-{secrets.token_hex(32)}.{worker_id.replace('wor_', '')[-8:]}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        async with async_session_factory() as db:
            worker = Worker(
                id=worker_id,
                name="B47 Other Agent",
                team_id=seed.team_id,
                actor_type=WorkerActorType.AGENT,
                status=WorkerStatus.ACTIVE,
                api_key_hash=key_hash,
            )
            db.add(worker)
            await db.commit()

        # Worker 尝试为 test_worker（另一个 Worker）创建 capability_exec
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,  # ← 不是自己
                "request_type": "capability_exec",
                "capability_id": "git_push_main",
                "operation": "git.push",
            },
            headers=auth_header(raw_key),
        )
        assert resp.status_code == 403, resp.text

    async def test_create_api_auth_as_worker_forbidden(
        self, client: AsyncClient, seed, test_project
    ):
        """Worker 创建 api_auth 请求 → 403。

        P11-B47: 非 capability_exec 类型不享受自请求旁路。
        Worker 仍需 admin/lead role 才能创建 api_auth 请求。
        （api_auth 由系统的 _trigger_authorization_flow 自动创建，Worker 不应手动创建）
        """
        import hashlib
        import secrets

        from src.constants import WorkerActorType, WorkerStatus
        from src.models.worker import Worker
        from src.utils.id_gen import generate_id

        worker_id = generate_id("worker")
        raw_key = f"sk-syn-{secrets.token_hex(32)}.{worker_id.replace('wor_', '')[-8:]}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        async with async_session_factory() as db:
            worker = Worker(
                id=worker_id,
                name="B47 No Role Agent",
                team_id=seed.team_id,
                actor_type=WorkerActorType.AGENT,
                status=WorkerStatus.ACTIVE,
                api_key_hash=key_hash,
            )
            db.add(worker)
            await db.commit()

        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": worker_id,
                "request_type": "api_auth",
                "operation": "test.no_role",
            },
            headers=auth_header(raw_key),
        )
        assert resp.status_code == 403, resp.text

    async def test_create_capability_exec_as_admin_for_worker(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """人类 admin 为 Worker 创建 capability_exec → 201。

        P11-B47: admin/lead 角色不受影响——仍可创建任何类型的授权请求，
        包括为 Worker 创建 capability_exec。
        """
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "capability_exec",
                "capability_id": "git_push_main",
                "operation": "git.push",
                "prompt_message": "Admin 为 Worker 创建的能力执行请求",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["request_type"] == "capability_exec"
        assert data["worker_id"] == test_worker
        assert data["capability_id"] == "git_push_main"


class TestListAuthRequests:
    """列出授权请求 API."""

    async def test_list_empty(
        self, client: AsyncClient, seed, test_project
    ):
        """新项目无请求 → 空列表."""
        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_filter_by_status(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """按状态筛选."""
        # 创建 pending 和 approved
        for i in range(2):
            resp = await client.post(
                f"/v1/projects/{test_project}/authorization-requests",
                json={
                    "project_id": test_project,
                    "worker_id": test_worker,
                    "request_type": "api_auth",
                    "operation": f"test.list.{i}",
                },
                headers=auth_header(seed.token),
            )
            assert resp.status_code == 201
            req_id = resp.json()["id"]

            if i == 0:
                # 批准第一个
                resp2 = await client.patch(
                    f"/v1/authorization-requests/{req_id}/respond",
                    json={"status": "approved"},
                    headers=auth_header(seed.token),
                )
                assert resp2.status_code == 200, resp2.text

        # 查 pending → 1 条
        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests?status=pending",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # 查 approved → 1 条
        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests?status=approved",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_exclude_expired_pending(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """P12-B39: 默认排除已过期的 pending 请求."""
        # 创建一个已过期的 pending 请求
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.expired",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201
        expired_id = resp.json()["id"]

        # 手动将 expires_at 设为过去时间
        from src.models.authorization_request import AuthorizationRequest
        async with async_session_factory() as db:
            from sqlalchemy import update as sql_update
            from datetime import datetime, timedelta, timezone
            await db.execute(
                sql_update(AuthorizationRequest)
                .where(AuthorizationRequest.id == expired_id)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
            )
            await db.commit()

        # 默认 include_expired=false → 不返回过期请求
        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests?status=pending",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert expired_id not in ids, "过期请求不应出现在默认 pending 列表中"

        # include_expired=true → 返回过期请求
        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests?status=pending&include_expired=true",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert expired_id in ids, "include_expired=true 时应返回过期请求"

        # Cleanup: delete expired request to avoid polluting other tests
        async with async_session_factory() as db:
            from src.models.authorization_request import AuthorizationRequest as AR
            from sqlalchemy import delete as sql_delete
            await db.execute(sql_delete(AR).where(AR.id == expired_id))
            await db.commit()

    async def test_list_pagination(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """分页功能."""
        for i in range(5):
            resp = await client.post(
                f"/v1/projects/{test_project}/authorization-requests",
                json={
                    "project_id": test_project,
                    "worker_id": test_worker,
                    "request_type": "api_auth",
                    "operation": f"test.page.{i}",
                },
                headers=auth_header(seed.token),
            )
            assert resp.status_code == 201

        # limit=3 → 3 条
        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests?limit=3&offset=0",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3

        # offset=3 → 2 条
        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests?limit=3&offset=3",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_requires_project_role(
        self, client: AsyncClient, seed, test_project
    ):
        """无 project role → 403."""
        async with async_session_factory() as db:
            from sqlalchemy import delete
            await db.execute(
                delete(ProjectActorRole).where(
                    ProjectActorRole.project_id == test_project,
                    ProjectActorRole.worker_id == seed.worker_id,
                )
            )
            await db.commit()

        resp = await client.get(
            f"/v1/projects/{test_project}/authorization-requests",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# PATCH /authorization-requests/{id}/respond
# ═══════════════════════════════════════════════════════════════════


class TestRespondToAuthRequest:
    """响应授权请求 API."""

    async def test_approve(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """批准 pending 请求."""
        # 创建
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.approve",
            },
            headers=auth_header(seed.token),
        )
        req_id = resp.json()["id"]

        # 批准
        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/respond",
            json={"status": "approved", "response_note": "已批准"},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 200, resp2.text
        data = resp2.json()
        assert data["status"] == "approved"
        assert data["response_note"] == "已批准"
        assert data["responded_by_worker_id"] == seed.worker_id
        assert data["responded_at"] is not None

    async def test_deny(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """拒绝 pending 请求."""
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.deny",
            },
            headers=auth_header(seed.token),
        )
        req_id = resp.json()["id"]

        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/respond",
            json={"status": "denied", "response_note": "权限不足"},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "denied"

    async def test_cannot_respond_twice(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """同一请求不能响应两次."""
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.double",
            },
            headers=auth_header(seed.token),
        )
        req_id = resp.json()["id"]

        # 第一次
        r1 = await client.patch(
            f"/v1/authorization-requests/{req_id}/respond",
            json={"status": "approved"},
            headers=auth_header(seed.token),
        )
        assert r1.status_code == 200

        # 第二次 → 400（状态机拒绝）
        r2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/respond",
            json={"status": "denied"},
            headers=auth_header(seed.token),
        )
        assert r2.status_code == 400
        assert "INVALID_STATUS_TRANSITION" in r2.json()["error"]["code"]

    async def test_respond_nonexistent(
        self, client: AsyncClient, seed
    ):
        """响应不存在的请求 → 404."""
        resp = await client.patch(
            "/v1/authorization-requests/areq_nonexistent/respond",
            json={"status": "approved"},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 404

    async def test_respond_without_project_role(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """无 project role → 403."""
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,
                "request_type": "api_auth",
                "operation": "test.no_role_resp",
            },
            headers=auth_header(seed.token),
        )
        req_id = resp.json()["id"]

        # 删除 project role
        async with async_session_factory() as db:
            from sqlalchemy import delete
            await db.execute(
                delete(ProjectActorRole).where(
                    ProjectActorRole.project_id == test_project,
                    ProjectActorRole.worker_id == seed.worker_id,
                )
            )
            await db.commit()

        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/respond",
            json={"status": "approved"},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# PATCH /authorization-requests/{id}/heartbeat
# ═══════════════════════════════════════════════════════════════════


class TestHeartbeatAuthRequest:
    """心跳续期 API."""

    async def test_heartbeat_as_owner(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """请求拥有者（worker_id == actor_id）可以发心跳."""
        # 创建请求的 worker_id = seed.worker_id（actor 自己）
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": seed.worker_id,  # actor 自己
                "request_type": "api_auth",
                "operation": "test.hb_own",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        req_id = resp.json()["id"]

        original_hb = resp.json()["last_heartbeat_at"]

        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/heartbeat",
            json={},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 200, resp2.text
        # 心跳不一定改变时间戳（太快了），但状态保持 pending
        assert resp2.json()["status"] == "pending"

    async def test_heartbeat_not_owner(
        self, client: AsyncClient, seed, test_project, test_worker
    ):
        """非拥有者 → 403."""
        # 创建请求的 worker_id = test_worker（不是 actor）
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": test_worker,  # 不是 seed.worker_id
                "request_type": "api_auth",
                "operation": "test.hb_not_owner",
            },
            headers=auth_header(seed.token),
        )
        req_id = resp.json()["id"]

        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/heartbeat",
            json={},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 403
        assert "NOT_REQUEST_OWNER" in resp2.json()["error"]["code"]

    async def test_heartbeat_non_pending(
        self, client: AsyncClient, seed, test_project
    ):
        """非 pending 请求心跳 → 400."""
        # 创建请求
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": seed.worker_id,
                "request_type": "api_auth",
                "operation": "test.hb_done",
            },
            headers=auth_header(seed.token),
        )
        req_id = resp.json()["id"]

        # 先批准
        await client.patch(
            f"/v1/authorization-requests/{req_id}/respond",
            json={"status": "approved"},
            headers=auth_header(seed.token),
        )

        # 心跳 → 400
        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/heartbeat",
            json={},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 400

    async def test_heartbeat_nonexistent(
        self, client: AsyncClient, seed
    ):
        """不存在的请求 → 404."""
        resp = await client.patch(
            "/v1/authorization-requests/areq_nonexistent/heartbeat",
            json={},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 404

    async def test_heartbeat_without_project_role_non_api_auth(
        self, client: AsyncClient, seed, test_project
    ):
        """S-064: 非 api_auth 请求，已撤销 project role → heartbeat 403."""
        # 创建 interactive_prompt 请求
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": seed.worker_id,
                "request_type": "interactive_prompt",
                "prompt_type": "confirm",
                "prompt_message": "Test heartbeat without project role",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        req_id = resp.json()["id"]

        # 确认有心跳权限（actor 是 owner 且有 project role）
        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/heartbeat",
            json={},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 200, resp2.text

        # 删除 seed 的 project role
        async with async_session_factory() as db:
            from sqlalchemy import delete

            await db.execute(
                delete(ProjectActorRole).where(
                    ProjectActorRole.project_id == test_project,
                    ProjectActorRole.worker_id == seed.worker_id,
                )
            )
            await db.commit()

        # 心跳 → 403（非 api_auth 类型，需 project 成员身份）
        resp3 = await client.patch(
            f"/v1/authorization-requests/{req_id}/heartbeat",
            json={},
            headers=auth_header(seed.token),
        )
        assert resp3.status_code == 403
        assert "NOT_PROJECT_MEMBER" in resp3.json()["error"]["code"]

    async def test_heartbeat_api_auth_no_role_still_works(
        self, client: AsyncClient, seed, test_project
    ):
        """S-064: api_auth 请求，无 project role 心跳仍有效（首角色申请中）."""
        # 创建 api_auth 请求（worker_id=seed.worker_id）
        resp = await client.post(
            f"/v1/projects/{test_project}/authorization-requests",
            json={
                "project_id": test_project,
                "worker_id": seed.worker_id,
                "request_type": "api_auth",
                "operation": "test.hb_api_auth_no_role",
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        req_id = resp.json()["id"]

        # 删除 seed 的 project role（模拟 Worker 申请首角色的场景）
        async with async_session_factory() as db:
            from sqlalchemy import delete

            await db.execute(
                delete(ProjectActorRole).where(
                    ProjectActorRole.project_id == test_project,
                    ProjectActorRole.worker_id == seed.worker_id,
                )
            )
            await db.commit()

        # api_auth 类型：即使无 project role，心跳仍应有效
        # （Worker 正在等待首角色审批，尚未有 project role）
        resp2 = await client.patch(
            f"/v1/authorization-requests/{req_id}/heartbeat",
            json={},
            headers=auth_header(seed.token),
        )
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["status"] == "pending"
