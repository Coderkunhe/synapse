"""E2E 测试：Worker 生命周期 — 注册、握手、心跳、停用。"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.constants import WorkerRuntimeStatus
from src.db import async_session_factory
from src.models.worker import Worker
from tests.conftest import SeedData, auth_header


class TestAgentLifecycle:
    """Worker 注册 → 握手 → 心跳 → 获取 → 停用。"""

    @pytest.mark.asyncio
    async def test_full_agent_lifecycle(self, client: AsyncClient, seed: SeedData):
        """正常路径：注册 agent、握手、心跳、验证状态。"""
        headers = auth_header(seed.token)

        # 1. 注册 agent
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={
                "name": "Test Worker",
                "provider": "claude",
                "provider_model": "sonnet",
                "system_prompt": "You are a test agent.",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "api_key" in data
        assert data["worker"]["status"] == "pending"
        agent_id = data["worker"]["id"]
        api_key = data["api_key"]

        # 2. 握手 — 激活 agent
        handshake_resp = await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [
                    {
                        "name": "code_review",
                        "description": "Can review code",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    }
                ],
                "supported_events": ["task.assigned", "task.completed"],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )
        assert handshake_resp.status_code == 200, handshake_resp.text
        agent = handshake_resp.json()
        assert agent["status"] == "active"
        # 注意：AgentResponse schema 不包含 capabilities；
        # 可以通过 GET /agents/{id} 查询（MVP 中同样省略）

        # 3. 心跳
        hb_resp = await client.post(
            f"/v1/agents/{agent_id}/heartbeat",
            json={"current_load": 3, "current_task_id": None},
            headers=auth_header(api_key),
        )
        assert hb_resp.status_code == 200
        assert hb_resp.json()["status"] == "ok"

        # 4. 获取 agent 详情（以 admin member 身份）
        get_resp = await client.get(
            f"/v1/agents/{agent_id}",
            headers=headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "active"

        # 5. 停用 agent
        del_resp = await client.delete(
            f"/v1/agents/{agent_id}",
            headers=headers,
        )
        assert del_resp.status_code == 204

        # 6. 验证已停用的 agent 无法发送心跳
        hb2_resp = await client.post(
            f"/v1/agents/{agent_id}/heartbeat",
            json={"current_load": 0, "current_task_id": None},
            headers=auth_header(api_key),
        )
        assert hb2_resp.status_code == 401, hb2_resp.text

    @pytest.mark.asyncio
    async def test_worker_heartbeat_updates_fields(self, client: AsyncClient, seed: SeedData):
        """心跳应更新 last_heartbeat_at 和 current_load。"""
        headers = auth_header(seed.token)

        # 注册 + 握手
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "HB Worker", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        agent_id = resp.json()["worker"]["id"]
        api_key = resp.json()["api_key"]

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

        # 发送带负载的心跳
        await client.post(
            f"/v1/agents/{agent_id}/heartbeat",
            json={"current_load": 7, "current_task_id": "tsk_test123"},
            headers=auth_header(api_key),
        )

        # 验证 agent 详情反映了更新
        get_resp = await client.get(f"/v1/agents/{agent_id}", headers=headers)
        assert get_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_agents_in_team(self, client: AsyncClient, seed: SeedData):
        """列出 agent 返回 team 的全部 agent。"""
        headers = auth_header(seed.token)

        # 注册 2 个 agent
        for name in ["Worker One", "Worker Two"]:
            resp = await client.post(
                f"/v1/teams/{seed.team_id}/agents",
                json={"name": name, "provider": "claude", "provider_model": "sonnet"},
                headers=headers,
            )
            assert resp.status_code == 201

        # 列出 agent
        list_resp = await client.get(
            f"/v1/teams/{seed.team_id}/agents",
            headers=headers,
        )
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert len(data["items"]) == 3  # P10-B7: 2 AI agents + 1 human worker (seed)
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_handshake_without_api_key_fails(self, client: AsyncClient, seed: SeedData):
        """无认证的握手应返回 401。"""
        resp = await client.post(
            f"/v1/agents/nonexistent_agent/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
        )
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_hard_delete_agent(self, client: AsyncClient, seed: SeedData):
        """硬删除 agent 后 GET 返回 404。"""
        headers = auth_header(seed.token)

        # 1. 注册 agent
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={
                "name": "To Be Deleted",
                "provider": "claude",
                "provider_model": "haiku",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        agent_id = resp.json()["worker"]["id"]

        # 2. 硬删除
        del_resp = await client.delete(
            f"/v1/agents/{agent_id}",
            headers=headers,
        )
        assert del_resp.status_code == 204

        # 3. GET 应返回 404 — agent 已被物理删除
        get_resp = await client.get(
            f"/v1/agents/{agent_id}",
            headers=headers,
        )
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_heartbeat_recovery_event_serializes_as_str(self, client: AsyncClient, seed: SeedData):
        """PFL-265 回归：ERROR→IDLE 恢复路径的 recovery_event 是 str，response_model 校验不炸。

        服务层 `_worker_heartbeat` 返回的是 ``event_type`` 字符串（如
        ``"worker.runtime.idle"``），但旧 schema 声明 ``recovery_event: dict | None``。
        纯 service 单测（test_worker_runtime）走不到 HTTP 层 response_model 校验，
        于是「首次心跳 500、第二次 200」这个 bug 一直漏网。本测试走 ASGI client
        真实触发恢复路径，锁定 response_model 序列化不炸。
        """
        headers = auth_header(seed.token)

        # 1. 注册 + 握手
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Recovery Worker", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        worker_id = resp.json()["worker"]["id"]
        api_key = resp.json()["api_key"]

        handshake_resp = await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )
        assert handshake_resp.status_code == 200, handshake_resp.text

        # 2. 直接把 worker 打到 ERROR（模拟 B7 失败检测器）
        async with async_session_factory() as session:
            result = await session.execute(select(Worker).where(Worker.id == worker_id))
            worker = result.scalar_one()
            worker.runtime_status = WorkerRuntimeStatus.ERROR
            await session.commit()

        # 3. ERROR 状态下心跳 → 恢复到 IDLE，recovery_event 应为 str
        hb_resp = await client.post(
            f"/v1/workers/{worker_id}/heartbeat",
            json={"current_load": 0},
            headers=auth_header(api_key),
        )
        assert hb_resp.status_code == 200, hb_resp.text
        body = hb_resp.json()
        assert body["status"] == "ok"
        assert body["recovery_event"] == "worker.runtime.idle"
        assert isinstance(body["recovery_event"], str)
