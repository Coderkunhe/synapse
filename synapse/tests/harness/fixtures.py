"""Provider-aware Worker fixtures。

P13-B6: 构建在 conftest.py 现有 fixture 之上（D-P13-005: 不修改现有测试）。
每个 fixture 创建一个完整就绪的 Worker（注册+握手+心跳+项目角色分配）。

用法:
    from tests.harness.fixtures import claude_worker, codex_worker, multi_worker_env

    async def test_something(claude_worker, codex_worker):
        claude = claude_worker
        codex = codex_worker
        # 两个 Worker 均已注册、握手、心跳、分配 builder 角色
"""

from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ensure_project_role
from tests.harness.providers import claude_code_provider_config, codex_cli_provider_config


# ── 内部: Worker 完整生命周期创建 ─────────────────────────────

async def _create_provisioned_worker(
    client: AsyncClient,
    seed: SeedData,
    name: str,
    provider_config: dict,
) -> dict:
    """创建完整就绪的 Worker: 注册 → 握手 → 心跳 → 分配项目角色。

    Args:
        client: ASGI 测试客户端。
        seed: 播种数据（admin 权限）。
        name: Worker 名称。
        provider_config: Provider 配置 dict（来自 providers.py）。

    Returns:
        {"worker_id": ..., "api_key": ..., "project_id": ..., "config": ...}
    """
    headers = auth_header(seed.token)

    # 1. 创建 project（slug 用 uuid4 hex 保证唯一性）
    import uuid

    proj_slug = f"proj-{uuid.uuid4().hex[:8]}"
    proj_resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": f"Project-{name}", "slug": proj_slug},
        headers=headers,
    )
    assert proj_resp.status_code == 201, f"Project create failed: {proj_resp.text}"
    project_id = proj_resp.json()["id"]

    # 2. 注册 Worker（带 provider 类型 — 映射到 API Literal）
    # Provider config 的 "type" 是详细标识 (claude_code/codex_cli)，
    # API 的 provider 字段接受 Literal["claude", "codex", "custom"]。
    _api_provider_map = {
        "claude_code": "claude",
        "codex_cli": "codex",
    }
    api_provider = _api_provider_map.get(provider_config["type"], "custom")
    agent_resp = await client.post(
        f"/v1/teams/{seed.team_id}/agents",
        json={
            "name": name,
            "provider": api_provider,
            "provider_model": "default",
        },
        headers=headers,
    )
    assert agent_resp.status_code == 201, f"Worker register failed: {agent_resp.text}"
    data = agent_resp.json()
    worker_id = data["worker"]["id"]
    api_key = data["api_key"]

    # 3. Handshake
    hs_resp = await client.post(
        f"/v1/agents/{worker_id}/handshake",
        json={
            "worker_version": provider_config["version"],
            "capabilities": [],
            "supported_events": ["task.assigned", "task.completed"],
            "preferred_channel": "websocket",
        },
        headers=auth_header(api_key),
    )
    assert hs_resp.status_code == 200, f"Handshake failed: {hs_resp.text}"

    # 4. 初始心跳
    hb_resp = await client.post(
        f"/v1/agents/{worker_id}/heartbeat",
        json={"current_load": 0},
        headers=auth_header(api_key),
    )
    assert hb_resp.status_code == 200, f"Initial heartbeat failed: {hb_resp.text}"

    # 5. 分配项目角色
    await ensure_project_role(client, project_id, worker_id, "builder", headers)

    return {
        "worker_id": worker_id,
        "api_key": api_key,
        "project_id": project_id,
        "config": provider_config,
    }


# ── 单 Worker Fixtures ────────────────────────────────────────

@pytest_asyncio.fixture
async def claude_worker(client: AsyncClient, seed: SeedData) -> dict:
    """创建一个完整就绪的 Claude Code Worker。

    Returns:
        {"worker_id": ..., "api_key": ..., "project_id": ..., "config": ...}
    """
    return await _create_provisioned_worker(
        client, seed, "Claude-Builder", claude_code_provider_config()
    )


@pytest_asyncio.fixture
async def codex_worker(client: AsyncClient, seed: SeedData) -> dict:
    """创建一个完整就绪的 Codex CLI Worker。

    Returns:
        {"worker_id": ..., "api_key": ..., "project_id": ..., "config": ...}
    """
    return await _create_provisioned_worker(
        client, seed, "Codex-Builder", codex_cli_provider_config()
    )


# ── 多 Worker 环境 ────────────────────────────────────────────

@pytest_asyncio.fixture
async def multi_worker_env(client: AsyncClient, seed: SeedData) -> dict:
    """创建双 Worker 环境 — 1 Claude + 1 Codex。

    每个 Worker 独立 project，互相不污染（D-P13-005 隔离性原则）。

    Returns:
        {"claude": {...}, "codex": {...}, "seed": SeedData}
    """
    claude = await _create_provisioned_worker(
        client, seed, "Claude", claude_code_provider_config()
    )
    codex = await _create_provisioned_worker(
        client, seed, "Codex", codex_cli_provider_config()
    )
    return {"claude": claude, "codex": codex, "seed": seed}
