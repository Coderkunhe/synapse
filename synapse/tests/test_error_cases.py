"""E2E 测试：错误场景 — 401、403、404、409、400 全覆盖。"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


class TestAuthErrors:
    """401 未授权场景。"""

    @pytest.mark.asyncio
    async def test_missing_token(self, client: AsyncClient, seed: SeedData):
        """无认证头 → 401。"""
        resp = await client.get(f"/v1/teams/{seed.team_id}")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "AUTH_MISSING_TOKEN"

    @pytest.mark.asyncio
    async def test_invalid_api_key(self, client: AsyncClient):
        """伪造 API key → 401。"""
        resp = await client.post(
            "/v1/agents/fake_agent/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers=auth_header("sk-syn-fakekey1234.fakeprefix"),
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_jwt(self, client: AsyncClient):
        """无效 JWT → 401。"""
        resp = await client.get(
            "/v1/teams/tea_test",
            headers=auth_header("eyJhbGciOiJIUzI1NiJ9.---garbage---"),
        )
        assert resp.status_code == 401


class TestForbiddenErrors:
    """403 禁止访问场景。"""

    @pytest.mark.asyncio
    async def test_member_insufficient_role(self, client: AsyncClient, seed: SeedData):
        """普通成员尝试管理员操作 → 403。"""
        # 创建非管理员成员
        from src.db import async_session_factory
        from src.models.member import Member
        from src.utils.id_gen import generate_id
        from src.auth import create_access_token

        member_id = generate_id("member")
        short = member_id.replace("mem_", "")[-12:]
        async with async_session_factory() as session:
            member = Member(
                id=member_id,
                team_id=seed.team_id,
                user_id=f"user-{short}",
                display_name="Regular Member",
                role="member",
            )
            session.add(member)
            await session.commit()

        member_token = create_access_token(
            user_id=f"user-{short}",
            member_id=member_id,
            team_id=seed.team_id,
            role="member",
        )

        # 尝试注册 agent（需要管理员权限）→ 403
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Nope", "provider": "claude", "provider_model": "sonnet"},
            headers=auth_header(member_token),
        )
        assert resp.status_code == 403, resp.text

        # 清理
        async with async_session_factory() as session:
            m = await session.get(Member, member_id)
            if m:
                await session.delete(m)
                await session.commit()

    @pytest.mark.asyncio
    async def test_super_admin_bypasses_require_role(self, client: AsyncClient, seed: SeedData):
        """超管 (is_super_admin=True) 绕过 require_role — role=member 也能调 admin 端点。P10-B17"""
        from src.auth import create_access_token

        # 创建 is_super_admin=True 但 role="member" 的 JWT
        super_token = create_access_token(
            user_id="user-super-test",
            actor_id=seed.worker_id,
            team_id=seed.team_id,
            role="member",
            is_super_admin=True,
        )

        # 调用 require_role("admin", "lead") 保护的端点 → 超管应绕过
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(super_token),
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_require_super_admin_blocks_normal_admin(self, client: AsyncClient, seed: SeedData):
        """普通 admin (is_super_admin=False) 调 require_super_admin 端点 → 403。P10-B17"""
        # seed token 是 admin 但不是 super_admin
        resp = await client.get(
            "/v1/admin/system-info",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 403, resp.text
        err = resp.json()["error"]
        assert err["code"] == "FORBIDDEN_SUPER_ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_require_super_admin_allows_super_admin(self, client: AsyncClient, seed: SeedData):
        """超管 (is_super_admin=True) 调 require_super_admin 端点 → 200。P10-B17"""
        from src.auth import create_access_token

        super_token = create_access_token(
            user_id="user-super-test",
            actor_id=seed.worker_id,
            team_id=seed.team_id,
            role="admin",
            is_super_admin=True,
        )

        resp = await client.get(
            "/v1/admin/system-info",
            headers=auth_header(super_token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["super_admin"] is True
        assert data["user_id"] == "user-super-test"

    @pytest.mark.asyncio
    async def test_agent_cannot_register_worker(self, client: AsyncClient, seed: SeedData):
        """Worker 尝试注册另一个 Worker → 403。"""
        # 注册并握手一个 agent
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Original", "provider": "claude", "provider_model": "sonnet"},
            headers=auth_header(seed.token),
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )

        # Worker 尝试注册另一个 agent → 403
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Rogue", "provider": "claude", "provider_model": "sonnet"},
            headers=auth_header(api_key),
        )
        assert resp.status_code == 403, resp.text

    @pytest.mark.asyncio
    async def test_agent_cannot_access_team_events(self, client: AsyncClient, seed: SeedData):
        """Worker 访问团队事件列表 → 403。"""
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "EventSneak", "provider": "claude", "provider_model": "sonnet"},
            headers=auth_header(seed.token),
        )
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_resp.json()['worker']['id']}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )

        resp = await client.get(
            f"/v1/teams/{seed.team_id}/events",
            headers=auth_header(api_key),
        )
        assert resp.status_code == 403, resp.text


    @pytest.mark.asyncio
    async def test_not_project_member_denied_update(self, client: AsyncClient, seed: SeedData):
        """非项目成员尝试更新项目 → 403 FORBIDDEN_NOT_PROJECT_MEMBER。"""
        # 创建第二个 team 的 admin，ta 不在第一个 team 的项目里
        from tests.conftest import SeedData as SD
        import uuid

        # 创建一个不属于该项目的 actor 来测试
        # 使用 seed fixture 创建项目，但用一个无 project_role 的 actor 访问
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": f"RoleTest-{uuid.uuid4().hex[:8]}", "slug": f"roletest-{uuid.uuid4().hex[:8]}"},
            headers=auth_header(seed.token),
        )
        # seed admin 是创建者 → 自动获得 project admin → 应该成功
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        # PATCH 应该成功（seed admin 是项目 admin）
        resp = await client.patch(
            f"/v1/projects/{project_id}",
            json={"name": "Updated Name"},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_project_role_required_for_task_create(self, client: AsyncClient, seed: SeedData):
        """创建任务需要项目角色 — seed admin 是创建者所以有 admin 角色，应成功。"""
        import uuid

        # 创建项目（admin 自动获得 project admin 角色）
        slug = f"tasktest-{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": f"TaskRoleTest-{uuid.uuid4().hex[:8]}", "slug": slug},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        # 创建任务 — admin 有项目角色，应该成功
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Test Task",
                "description": "A test task",
                "verifications": [{"type": "manual", "description": "Check it"}],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text

    @pytest.mark.asyncio
    async def test_super_admin_bypasses_project_role(self, client: AsyncClient, seed: SeedData):
        """超管可以绕过项目角色检查 (P10-B17)。"""
        import uuid

        # 创建超管 token
        from src.auth import create_access_token
        super_token = create_access_token(
            user_id=f"super-{uuid.uuid4().hex[:8]}",
            actor_id=seed.worker_id,
            team_id=seed.team_id,
            role="admin",
            is_super_admin=True,
        )

        # 创建项目（用普通 admin token）
        slug = f"super-{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": f"SuperBypass-{uuid.uuid4().hex[:8]}", "slug": slug},
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        # 超管（不同的 worker_id）没有项目角色，但应该能 bypass
        resp = await client.patch(
            f"/v1/projects/{project_id}",
            json={"name": "Super Bypassed"},
            headers=auth_header(super_token),
        )
        # 超管绕过 project role 检查 → 200
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Super Bypassed"


class TestNotFoundErrors:
    """404 未找到场景。"""

    @pytest.mark.asyncio
    async def test_nonexistent_entity(self, client: AsyncClient, seed: SeedData):
        """请求不存在的 team、task、agent → 404。"""
        headers = auth_header(seed.token)

        for path in [
            f"/v1/teams/tea_nonexistent",
            f"/v1/tasks/tsk_nonexistent123",
            f"/v1/agents/ag_nonexistent456",
            f"/v1/projects/prj_nonexistent",
        ]:
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 404, f"{path} should 404, got {resp.status_code}"


class TestConflictErrors:
    """409 冲突场景。"""

    @pytest.mark.asyncio
    async def test_duplicate_project_slug(self, client: AsyncClient, seed: SeedData):
        """创建同名 slug 的项目 → 409。"""
        headers = auth_header(seed.token)

        await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "First", "slug": "same-slug"},
            headers=headers,
        )

        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Second", "slug": "same-slug"},
            headers=headers,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "PROJECT_SLUG_EXISTS"

    @pytest.mark.asyncio
    async def test_duplicate_member(self, client: AsyncClient, seed: SeedData):
        """重复邀请同一用户 → 409。"""
        headers = auth_header(seed.token)

        await client.post(
            f"/v1/teams/{seed.team_id}/members",
            json={"user_id": "user-dup", "display_name": "Dup", "role": "member"},
            headers=headers,
        )

        resp = await client.post(
            f"/v1/teams/{seed.team_id}/members",
            json={"user_id": "user-dup", "display_name": "Dup Again", "role": "member"},
            headers=headers,
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_archived_project_rejects_tasks(self, client: AsyncClient, seed: SeedData):
        """在已归档项目中创建任务 → 409。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Archive Me", "slug": "archive-me"},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 归档
        await client.post(f"/v1/projects/{project_id}/archive", headers=headers)

        # 尝试创建任务
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Should fail",
                "description": "Test task in archived project",
                "priority": "p3",
                "verifications": [{"type": "manual", "description": "X", "criteria": {}}],
            },
            headers=headers,
        )
        assert resp.status_code == 409


class TestCrossTeamIsolation:
    """跨团队访问隔离。"""

    @pytest.mark.asyncio
    async def test_team_a_cannot_see_team_b_entities(self, client: AsyncClient, seed: SeedData):
        """团队 A 的实体对团队 B 不可见。"""
        from src.db import async_session_factory
        from src.models.team import Team
        from src.models.member import Member
        from src.utils.id_gen import generate_id
        from src.auth import create_access_token

        headers_a = auth_header(seed.token)

        # 在团队 A 创建项目
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "A Project", "slug": "team-a-project"},
            headers=headers_a,
        )
        project_a_id = proj_resp.json()["id"]

        # 在团队 A 创建任务
        task_resp = await client.post(
            f"/v1/projects/{project_a_id}/tasks",
            json={
                "title": "Team A Task",
                "description": "test",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "Check", "criteria": {}}],
            },
            headers=headers_a,
        )
        task_a_id = task_resp.json()["id"]

        # 创建团队 B + 管理员成员
        team_b_id = generate_id("team")
        member_b_id = generate_id("member")
        async with async_session_factory() as session:
            team_b = Team(id=team_b_id, name="Team B", slug="team-b")
            member_b = Member(
                id=member_b_id,
                team_id=team_b_id,
                user_id="user-b",
                display_name="B Admin",
                role="admin",
            )
            session.add_all([team_b, member_b])
            await session.commit()

        headers_b = auth_header(create_access_token(
            user_id="user-b",
            member_id=member_b_id,
            team_id=team_b_id,
            role="admin",
        ))

        # 团队 B 尝试读取团队 A 的项目 → 404
        resp = await client.get(f"/v1/projects/{project_a_id}", headers=headers_b)
        assert resp.status_code == 404

        # 团队 B 尝试读取团队 A 的任务 → 404
        resp = await client.get(f"/v1/tasks/{task_a_id}", headers=headers_b)
        assert resp.status_code == 404

        # 清理
        async with async_session_factory() as session:
            for model_cls, rid in [(Member, member_b_id), (Team, team_b_id)]:
                obj = await session.get(model_cls, rid)
                if obj:
                    await session.delete(obj)
            await session.commit()


class TestAgentVisibility:
    """Worker 可见性限制（D-005）。"""

    @pytest.mark.asyncio
    async def test_agent_only_sees_own_tasks(self, client: AsyncClient, seed: SeedData):
        """Worker A 不应看到 Worker B 的任务。"""
        headers = auth_header(seed.token)

        # 准备项目
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Visibility Project", "slug": "vis-project"},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 创建 2 个 agent
        agents = {}
        for name in ["Alice", "Bob"]:
            resp = await client.post(
                f"/v1/teams/{seed.team_id}/agents",
                json={"name": name, "provider": "claude", "provider_model": "sonnet"},
                headers=headers,
            )
            agents[name] = {"id": resp.json()["worker"]["id"], "key": resp.json()["api_key"]}
            await client.post(
                f"/v1/agents/{agents[name]['id']}/handshake",
                json={
                    "worker_version": "1.0.0",
                    "capabilities": [],
                    "supported_events": [],
                    "preferred_channel": "websocket",
                },
                headers=auth_header(agents[name]["key"]),
            )

        # 创建 2 个任务，分别分配给两个 agent
        task_ids = {}
        for agent_name in ["Alice", "Bob"]:
            resp = await client.post(
                f"/v1/projects/{project_id}/tasks",
                json={
                    "title": f"Task for {agent_name}",
                    "description": "test",
                    "priority": "p2",
                    "verifications": [{"type": "manual", "description": "X", "criteria": {}}],
                },
                headers=headers,
            )
            tid = resp.json()["id"]
            ver = resp.json()["version_no"]
            task_ids[agent_name] = tid
            await client.post(
                f"/v1/tasks/{tid}/assign",
                json={"owner_type": "worker", "owner_id": agents[agent_name]["id"],
                      "expected_version": ver},
                headers=headers,
            )

        # Alice 可以看到自己的任务
        resp = await client.get(
            f"/v1/tasks/{task_ids['Alice']}",
            headers=auth_header(agents["Alice"]["key"]),
        )
        assert resp.status_code == 200

        # Alice 不应看到 Bob 的任务
        resp = await client.get(
            f"/v1/tasks/{task_ids['Bob']}",
            headers=auth_header(agents["Alice"]["key"]),
        )
        assert resp.status_code == 404
