"""审计字段接线测试 — 验证 create_user_id 从操作者正确传播。

这些测试填补了 ``create_user_id`` 静默默认为 ``"system"``
而非设置为执行创建操作的操作者的漏洞。它们是与静态
``check-schema-audit.py`` 门禁对应的运行时验证。
"""

from __future__ import annotations

import pytest

from tests.conftest import SeedData, auth_header


async def _create_entity(client, method: str, url: str, json: dict, headers: dict) -> dict:
    """辅助函数：创建实体并返回解析后的响应体。"""
    r = await getattr(client, method)(url, json=json, headers=headers)
    assert r.is_success, f"{method.upper()} {url} 失败：{r.text}"
    return r.json()


class TestCreateUserId:
    """每个创建实体的端点必须设置 ``create_user_id = actor_id``。"""

    async def test_project_create_user_id(self, client, seed: SeedData):
        h = auth_header(seed.token)
        body = {
            "name": "Audit Project",
            "slug": f"audit-{seed.team_id[-6:]}",
            "description": "create_user_id test",
        }
        data = await _create_entity(
            client, "post", f"/v1/teams/{seed.team_id}/projects", body, h,
        )
        assert data["create_user_id"] == seed.worker_id, (
            f"Project create_user_id={data['create_user_id']}, "
            f"期望 actor_id={seed.worker_id}"
        )

    async def test_batch_create_user_id(self, client, seed: SeedData):
        h = auth_header(seed.token)
        # 先创建一个项目
        proj = await _create_entity(
            client, "post", f"/v1/teams/{seed.team_id}/projects",
            {"name": "Audit Batch Proj", "slug": f"abp-{seed.team_id[-6:]}", "description": "t"}, h,
        )
        data = await _create_entity(
            client, "post", f"/v1/projects/{proj['id']}/batches",
            {"name": "Audit Batch", "description": "create_user_id test"}, h,
        )
        assert data["create_user_id"] == seed.worker_id, (
            f"Batch create_user_id={data['create_user_id']}"
        )

    async def test_task_create_user_id(self, client, seed: SeedData):
        h = auth_header(seed.token)
        proj = await _create_entity(
            client, "post", f"/v1/teams/{seed.team_id}/projects",
            {"name": "Audit Task Proj", "slug": f"atp-{seed.team_id[-6:]}", "description": "t"}, h,
        )
        data = await _create_entity(
            client, "post", f"/v1/projects/{proj['id']}/tasks",
            {
                "title": "Audit Task",
                "description": "create_user_id test",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "Check audit"}],
            }, h,
        )
        assert data["create_user_id"] == seed.worker_id, (
            f"Task create_user_id={data['create_user_id']}"
        )

    async def test_skill_create_user_id(self, client, seed: SeedData):
        h = auth_header(seed.token)
        data = await _create_entity(
            client, "post", f"/v1/teams/{seed.team_id}/skills",
            {
                "name": "Audit Skill",
                "template_md": "# Audit\nVerify audit trail.",
            }, h,
        )
        assert data["create_user_id"] == seed.worker_id, (
            f"Skill create_user_id={data['create_user_id']}"
        )

    async def test_agent_create_user_id(self, client, seed: SeedData):
        h = auth_header(seed.token)
        data = await _create_entity(
            client, "post", f"/v1/teams/{seed.team_id}/agents",
            {
                "name": "Audit Worker",
                "provider": "claude",
                "provider_model": "claude-sonnet-5",
            }, h,
        )
        agent = data["worker"]  # AgentCreateResponse 包装了 AgentResponse
        assert agent["create_user_id"] == seed.worker_id, (
            f"Worker create_user_id={agent['create_user_id']}"
        )

    async def test_analysis_create_user_id(self, client, seed: SeedData):
        h = auth_header(seed.token)
        proj = await _create_entity(
            client, "post", f"/v1/teams/{seed.team_id}/projects",
            {"name": "Audit Analysis Proj", "slug": f"aap-{seed.team_id[-6:]}", "description": "t"}, h,
        )
        data = await _create_entity(
            client, "post", f"/v1/projects/{proj['id']}/analyses",
            {
                "title": "Audit Analysis",
                "content": "Checking create_user_id propagation.",
                "analysis_type": "design",
            }, h,
        )
        assert data["create_user_id"] == seed.worker_id, (
            f"Analysis create_user_id={data['create_user_id']}"
        )

    async def test_scan_create_user_id(self, client, seed: SeedData):
        """ScanResult 也从操作者获取 create_user_id。"""
        h = auth_header(seed.token)
        proj = await _create_entity(
            client, "post", f"/v1/teams/{seed.team_id}/projects",
            {"name": "Audit Scan Proj", "slug": f"asp-{seed.team_id[-6:]}", "description": "t"}, h,
        )
        task = await _create_entity(
            client, "post", f"/v1/projects/{proj['id']}/tasks",
            {
                "title": "Audit Scan Task",
                "description": "t",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "Check"}],
            }, h,
        )
        data = await _create_entity(
            client, "post", f"/v1/scans/task/{task['id']}", {}, h,
        )
        assert data["create_user_id"] == seed.worker_id, (
            f"Scan create_user_id={data['create_user_id']}"
        )
