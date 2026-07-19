"""E2E 测试：AnalysisRecord — 创建、列表、详情、操作者追踪。"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    """生成唯一的项目 slug。"""
    from src.utils.id_gen import generate_id

    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestAnalysisRecord:
    """AnalysisRecord CRUD + 操作者可追溯性。"""

    @pytest.mark.asyncio
    async def test_create_analysis(self, client: AsyncClient, seed: SeedData):
        """创建一条分析记录并验证所有字段均已持久化。"""
        headers = auth_header(seed.token)

        # 准备：项目
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Analysis Test", "slug": _uniq_slug("analysis")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        # 创建分析记录
        resp = await client.post(
            f"/v1/projects/{project_id}/analyses",
            json={
                "analysis_type": "design",
                "title": "Architecture Decision: Event Sourcing",
                "content": "We decided to use event sourcing for audit trail.",
                "metadata": {"team": "backend", "priority": "high"},
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["project_id"] == project_id
        assert data["actor_type"] == "human"
        assert data["actor_id"] == seed.worker_id
        assert data["analysis_type"] == "design"
        assert data["title"] == "Architecture Decision: Event Sourcing"
        assert data["content"] == "We decided to use event sourcing for audit trail."
        assert data["metadata"] == {"team": "backend", "priority": "high"}
        assert data["source_batch_id"] is None
        assert data["id"].startswith("anl_")
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_list_analyses(self, client: AsyncClient, seed: SeedData):
        """使用游标分页 + 类型筛选列出分析记录。"""
        headers = auth_header(seed.token)

        # 准备：项目
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "List Test", "slug": _uniq_slug("list")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        # 创建 3 条分析记录：2 条 design、1 条 requirement
        for i in range(2):
            resp = await client.post(
                f"/v1/projects/{project_id}/analyses",
                json={
                    "analysis_type": "design",
                    "title": f"Design Analysis {i}",
                    "content": f"Design content {i}",
                },
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

        resp = await client.post(
            f"/v1/projects/{project_id}/analyses",
            json={
                "analysis_type": "requirement",
                "title": "Requirement Analysis",
                "content": "Req content",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

        # 列出全部 — 最新在前
        list_resp = await client.get(
            f"/v1/projects/{project_id}/analyses",
            headers=headers,
        )
        assert list_resp.status_code == 200, list_resp.text
        data = list_resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3
        # 最新在前：requirement、design 1、design 0
        assert data["items"][0]["analysis_type"] == "requirement"

        # 按类型筛选
        filter_resp = await client.get(
            f"/v1/projects/{project_id}/analyses?analysis_type=design",
            headers=headers,
        )
        assert filter_resp.status_code == 200, filter_resp.text
        data = filter_resp.json()
        assert data["total"] == 2
        assert all(item["analysis_type"] == "design" for item in data["items"])

    @pytest.mark.asyncio
    async def test_get_analysis_cross_team_returns_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """跨 team 访问分析记录应返回 404。"""
        headers = auth_header(seed.token)

        # 准备：seed 所属 team 的项目 + 分析记录
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Cross-team Test", "slug": _uniq_slug("cross")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        create_resp = await client.post(
            f"/v1/projects/{project_id}/analyses",
            json={
                "analysis_type": "discussion",
                "title": "Team Discussion",
                "content": "Discussion content here.",
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        analysis_id = create_resp.json()["id"]

        # 创建第二个 team
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(id=team2_id, name=f"Other Team {short}", slug=f"other-{short}")
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="Other Admin",
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

        # Team 2 尝试访问 Team 1 的分析记录 → 404
        get_resp = await client.get(
            f"/v1/analyses/{analysis_id}",
            headers=headers2,
        )
        assert get_resp.status_code == 404, get_resp.text

    @pytest.mark.asyncio
    async def test_analysis_actor_tracking(
        self, client: AsyncClient, seed: SeedData
    ):
        """验证 actor_type + actor_id 从认证上下文中正确记录。"""
        headers = auth_header(seed.token)

        # 准备：项目
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Actor Tracking", "slug": _uniq_slug("actor")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        # 以 member 身份创建（seed token）
        resp = await client.post(
            f"/v1/projects/{project_id}/analyses",
            json={
                "analysis_type": "requirement",
                "title": "Auth Context Test",
                "content": "Verify actor tracking.",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["actor_type"] == "human"
        assert data["actor_id"] == seed.worker_id
