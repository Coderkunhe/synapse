"""E2E 测试: Skill CRUD — 创建、列表、获取、更新、团队隔离。"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    from src.utils.id_gen import generate_id

    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestSkillCreate:
    """POST /teams/{team_id}/skills — 创建 Skill 定义。"""

    @pytest.mark.asyncio
    async def test_create_skill_minimal(
        self, client: AsyncClient, seed: SeedData
    ):
        """仅含必填字段的最小化 Skill 创建。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "代码审查 Skill",
                "template_md": "# 代码审查\n\n审查 Pull Request。",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["id"].startswith("skl_")
        assert data["team_id"] == seed.team_id
        assert data["name"] == "代码审查 Skill"
        assert data["version"] == "1.0.0"
        assert data["status"] == "active"
        assert data["template_md"] == "# 代码审查\n\n审查 Pull Request。"
        assert data["protocol_spec"] is None
        assert data["scan_rule_ids"] is None
        assert data["metadata"] is None
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_create_skill_full(
        self, client: AsyncClient, seed: SeedData
    ):
        """包含全部可选字段的 Skill 创建。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "完整 Skill",
                "version": "2.0.0",
                "template_md": "# 完整\n\n所有字段均已填写。",
                "protocol_spec": {"input": "task_id", "output": "verdict"},
                "scan_rule_ids": ["r1", "r2"],
                "metadata": {"owner": "platform"},
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["name"] == "完整 Skill"
        assert data["version"] == "2.0.0"
        assert data["template_md"] == "# 完整\n\n所有字段均已填写。"
        assert data["protocol_spec"] == {"input": "task_id", "output": "verdict"}
        assert data["scan_rule_ids"] == ["r1", "r2"]
        assert data["metadata"] == {"owner": "platform"}

    @pytest.mark.asyncio
    async def test_create_skill_missing_required_returns_422(
        self, client: AsyncClient, seed: SeedData
    ):
        """缺少 template_md 返回 422。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={"name": "不完整"},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_create_skill_cross_team_returns_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """在其他团队中创建 Skill 返回 404。"""
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(
                id=team2_id, name=f"其他团队 {short}", slug=f"other-{short}"
            )
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="其他管理员",
                role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}",
            member_id=member2_id,
            team_id=team2_id,
            role="admin",
        )
        headers2 = auth_header(token2)

        resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "跨团队 Skill",
                "template_md": "# 恶意\n\n尝试在其他团队中创建。",
            },
            headers=headers2,
        )
        assert resp.status_code == 404, resp.text


class TestSkillList:
    """GET /teams/{team_id}/skills — 带分页和过滤的列表。"""

    @pytest.mark.asyncio
    async def test_list_skills_empty(
        self, client: AsyncClient, seed: SeedData
    ):
        """没有 Skill 的团队列表返回空。"""
        headers = auth_header(seed.token)

        resp = await client.get(
            f"/v1/teams/{seed.team_id}/skills", headers=headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0
        assert data["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_list_skills(
        self, client: AsyncClient, seed: SeedData
    ):
        """列表返回团队所有 Skill，最新在前。"""
        headers = auth_header(seed.token)

        for i in range(3):
            resp = await client.post(
                f"/v1/teams/{seed.team_id}/skills",
                json={
                    "name": f"Skill {i}",
                    "template_md": f"# Skill {i}\n\n描述 {i}。",
                },
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

        resp = await client.get(
            f"/v1/teams/{seed.team_id}/skills", headers=headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3
        for item in data["items"]:
            assert item["id"].startswith("skl_")
            assert item["team_id"] == seed.team_id

    @pytest.mark.asyncio
    async def test_list_skills_filter_by_status(
        self, client: AsyncClient, seed: SeedData
    ):
        """按状态过滤仅返回匹配的 Skill。"""
        headers = auth_header(seed.token)

        # 创建活跃 Skill
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "活跃 Skill",
                "template_md": "# 活跃\n\n这个是活跃的。",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        skill_id = resp.json()["id"]

        # 弃用它
        patch_resp = await client.patch(
            f"/v1/skills/{skill_id}",
            json={"status": "deprecated"},
            headers=headers,
        )
        assert patch_resp.status_code == 200, patch_resp.text

        # 仅列出活跃 → 空
        resp_active = await client.get(
            f"/v1/teams/{seed.team_id}/skills?status=active",
            headers=headers,
        )
        assert resp_active.status_code == 200, resp_active.text
        assert resp_active.json()["total"] == 0

        # 仅列出已弃用 → 有 1 个
        resp_dep = await client.get(
            f"/v1/teams/{seed.team_id}/skills?status=deprecated",
            headers=headers,
        )
        assert resp_dep.status_code == 200, resp_dep.text
        assert resp_dep.json()["total"] == 1
        assert resp_dep.json()["items"][0]["status"] == "deprecated"

    @pytest.mark.asyncio
    async def test_list_skills_cursor_pagination(
        self, client: AsyncClient, seed: SeedData
    ):
        """游标分页: 创建 3 个 Skill，limit=2，验证游标行为。"""
        import asyncio

        headers = auth_header(seed.token)

        for i in range(3):
            resp = await client.post(
                f"/v1/teams/{seed.team_id}/skills",
                json={
                    "name": f"游标 Skill {i}",
                    "template_md": f"# 游标 {i}\n\n测试。",
                },
                headers=headers,
            )
            assert resp.status_code == 201, resp.text
            await asyncio.sleep(0.01)

        # 第 1 页
        resp1 = await client.get(
            f"/v1/teams/{seed.team_id}/skills?limit=2",
            headers=headers,
        )
        assert resp1.status_code == 200, resp1.text
        data1 = resp1.json()
        assert len(data1["items"]) == 2
        assert data1["next_cursor"] is not None
        assert data1["total"] == 3

        # 第 2 页
        resp2 = await client.get(
            f"/v1/teams/{seed.team_id}/skills?limit=2&cursor={data1['next_cursor']}",
            headers=headers,
        )
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()
        assert len(data2["items"]) == 1
        assert data2["total"] == 3

    @pytest.mark.asyncio
    async def test_list_skills_team_isolation(
        self, client: AsyncClient, seed: SeedData
    ):
        """团队 A 的 Skill 对团队 B 不可见。"""
        headers1 = auth_header(seed.token)

        resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "团队 1 Skill",
                "template_md": "# 团队 1\n\n机密 Skill。",
            },
            headers=headers1,
        )
        assert resp.status_code == 201, resp.text

        # 创建第二个团队
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(
                id=team2_id, name=f"其他团队 {short}", slug=f"other-{short}"
            )
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="其他管理员",
                role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}",
            member_id=member2_id,
            team_id=team2_id,
            role="admin",
        )
        headers2 = auth_header(token2)

        # 团队 2 列出 Skill — 应为空
        resp = await client.get(
            f"/v1/teams/{team2_id}/skills", headers=headers2
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0


class TestSkillGet:
    """GET /skills/{skill_id} — 按 ID 检索。"""

    @pytest.mark.asyncio
    async def test_get_skill_by_id(
        self, client: AsyncClient, seed: SeedData
    ):
        """GET /skills/{id} 返回完整 SkillResponse。"""
        headers = auth_header(seed.token)

        create_resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "获取我",
                "template_md": "# 获取我\n\n检索此 Skill。",
                "protocol_spec": {"key": "value"},
                "scan_rule_ids": ["rule-1"],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        skill_id = create_resp.json()["id"]

        resp = await client.get(f"/v1/skills/{skill_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["id"] == skill_id
        assert data["team_id"] == seed.team_id
        assert data["name"] == "获取我"
        assert data["protocol_spec"] == {"key": "value"}
        assert data["scan_rule_ids"] == ["rule-1"]

    @pytest.mark.asyncio
    async def test_get_skill_not_found(self, client: AsyncClient, seed: SeedData):
        """不存在的 Skill ID 返回 404。"""
        headers = auth_header(seed.token)
        resp = await client.get("/v1/skills/skl_nonexistent01", headers=headers)
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_get_skill_cross_team_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """跨团队访问 Skill 返回 404。"""
        headers1 = auth_header(seed.token)

        create_resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "团队 1 机密",
                "template_md": "# 机密\n\n仅团队 1 应能看到此内容。",
            },
            headers=headers1,
        )
        assert create_resp.status_code == 201, create_resp.text
        skill_id = create_resp.json()["id"]

        # 创建第二个团队
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(
                id=team2_id, name=f"其他团队 {short}", slug=f"other-{short}"
            )
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="其他管理员",
                role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}",
            member_id=member2_id,
            team_id=team2_id,
            role="admin",
        )
        headers2 = auth_header(token2)

        resp = await client.get(f"/v1/skills/{skill_id}", headers=headers2)
        assert resp.status_code == 404, resp.text


class TestSkillUpdate:
    """PATCH /skills/{skill_id} — 更新字段。"""

    @pytest.mark.asyncio
    async def test_update_skill_name(
        self, client: AsyncClient, seed: SeedData
    ):
        """仅更新名称。"""
        headers = auth_header(seed.token)

        create_resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "旧名称",
                "template_md": "# 旧\n\n将被重命名。",
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        skill_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/v1/skills/{skill_id}",
            json={"name": "新名称"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "新名称"
        # 其他字段不变
        assert data["template_md"] == "# 旧\n\n将被重命名。"
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_update_skill_deprecate(
        self, client: AsyncClient, seed: SeedData
    ):
        """弃用 Skill 将 status 设为 deprecated。"""
        headers = auth_header(seed.token)

        create_resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "待弃用",
                "template_md": "# 弃用\n\n旧协议。",
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        skill_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/v1/skills/{skill_id}",
            json={"status": "deprecated"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "deprecated"

    @pytest.mark.asyncio
    async def test_update_skill_all_fields(
        self, client: AsyncClient, seed: SeedData
    ):
        """一次性更新所有可更新字段。"""
        headers = auth_header(seed.token)

        create_resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "原始",
                "template_md": "# 原始\n\n原始内容。",
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        skill_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/v1/skills/{skill_id}",
            json={
                "name": "已更新",
                "version": "3.0.0",
                "template_md": "# 已更新\n\n新内容。",
                "protocol_spec": {"new": "spec"},
                "scan_rule_ids": ["new-rule"],
                "metadata": {"updated": True},
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["name"] == "已更新"
        assert data["version"] == "3.0.0"
        assert data["template_md"] == "# 已更新\n\n新内容。"
        assert data["protocol_spec"] == {"new": "spec"}
        assert data["scan_rule_ids"] == ["new-rule"]
        assert data["metadata"] == {"updated": True}

    @pytest.mark.asyncio
    async def test_update_skill_not_found(
        self, client: AsyncClient, seed: SeedData
    ):
        """更新不存在的 Skill 返回 404。"""
        headers = auth_header(seed.token)
        resp = await client.patch(
            "/v1/skills/skl_nonexistent01",
            json={"name": "幽灵"},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_update_skill_cross_team_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """跨团队更新返回 404。"""
        headers1 = auth_header(seed.token)

        create_resp = await client.post(
            f"/v1/teams/{seed.team_id}/skills",
            json={
                "name": "团队 1 Skill",
                "template_md": "# T1\n\n属于团队 1。",
            },
            headers=headers1,
        )
        assert create_resp.status_code == 201, create_resp.text
        skill_id = create_resp.json()["id"]

        # 创建第二个团队
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(
                id=team2_id, name=f"其他团队 {short}", slug=f"other-{short}"
            )
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="其他管理员",
                role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}",
            member_id=member2_id,
            team_id=team2_id,
            role="admin",
        )
        headers2 = auth_header(token2)

        resp = await client.patch(
            f"/v1/skills/{skill_id}",
            json={"name": "被黑"},
            headers=headers2,
        )
        assert resp.status_code == 404, resp.text
