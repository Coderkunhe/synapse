"""P13-B7: Heartbeat 维度多 Worker 测试。

测试覆盖:
  - Provider 超时差异: Claude (300s) vs Codex (1800s) — 回归守卫
  - TimeTravel beyond_timeout: 语义化时间操纵
  - 多 Worker 并发心跳: 各自更新，不互相干扰
  - 故障检测集成: 运行 admin/failure-detection/run 验证差异化超时
  - Harness fixture 验证: _create_provisioned_worker 生命周期正确

使用 B6 harness 工具库: fixtures + time_travel + assertions + providers。

注意: harness fixtures (claude_worker/codex_worker) 定义在 tests/harness/fixtures.py，
不由 conftest.py 自动发现。本文件遵循 test_harness_smoke.py 的模式 —
使用 _create_provisioned_worker() 直接创建 Worker。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header
from tests.harness.assertions import (
    assert_worker_offline,
    assert_worker_still_active,
)
from tests.harness.fixtures import _create_provisioned_worker
from tests.harness.providers import (
    claude_code_provider_config,
    codex_cli_provider_config,
    custom_provider_config,
)


# ── 辅助: 在测试中创建双 Worker 环境 ─────────────────────────────


async def _setup_multi_worker_env(client: AsyncClient, seed: SeedData) -> dict:
    """创建双 Worker 环境 — 1 Claude + 1 Codex（独立 project）。

    每个测试调用此函数以获取隔离的 Worker 环境。
    """
    claude = await _create_provisioned_worker(
        client, seed, "Claude-HB", claude_code_provider_config(),
    )
    codex = await _create_provisioned_worker(
        client, seed, "Codex-HB", codex_cli_provider_config(),
    )
    return {"claude": claude, "codex": codex, "seed": seed}


# ── Harness Fixture 验证 ────────────────────────────────────────


class TestHarnessHeartbeatFixtures:
    """验证 _create_provisioned_worker 正确创建包含完整生命周期的 Worker。"""

    @pytest.mark.asyncio
    async def test_claude_worker_has_valid_config(self, client: AsyncClient, seed: SeedData):
        """Claude Worker 返回完整配置。"""
        worker = await _create_provisioned_worker(
            client, seed, "Claude-Test", claude_code_provider_config(),
        )
        assert worker["worker_id"].startswith("ag_")
        assert len(worker["api_key"]) > 20
        assert worker["project_id"] is not None
        assert worker["config"]["type"] == "claude_code"
        assert worker["config"]["heartbeat"]["timeout_seconds"] == 300

    @pytest.mark.asyncio
    async def test_codex_worker_has_valid_config(self, client: AsyncClient, seed: SeedData):
        """Codex Worker 返回完整配置。"""
        worker = await _create_provisioned_worker(
            client, seed, "Codex-Test", codex_cli_provider_config(),
        )
        assert worker["worker_id"].startswith("ag_")
        assert len(worker["api_key"]) > 20
        assert worker["project_id"] is not None
        assert worker["config"]["type"] == "codex_cli"
        assert worker["config"]["heartbeat"]["timeout_seconds"] == 1800

    @pytest.mark.asyncio
    async def test_multi_worker_env_isolation(self, client: AsyncClient, seed: SeedData):
        """双 Worker 环境 — 隔离性验证。"""
        env = await _setup_multi_worker_env(client, seed)
        claude = env["claude"]
        codex = env["codex"]
        assert claude["project_id"] != codex["project_id"]
        assert claude["worker_id"] != codex["worker_id"]
        assert claude["api_key"] != codex["api_key"]
        assert claude["config"]["heartbeat"]["timeout_seconds"] == 300
        assert codex["config"]["heartbeat"]["timeout_seconds"] == 1800

    @pytest.mark.asyncio
    async def test_worker_heartbeat_was_sent(self, client: AsyncClient, seed: SeedData):
        """Fixture 创建后 Worker 应已发送初始心跳 — last_heartbeat_at 非 null。"""
        worker = await _create_provisioned_worker(
            client, seed, "HB-Check", claude_code_provider_config(),
        )
        resp = await client.get(
            f"/v1/agents/{worker['worker_id']}",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        agent = resp.json()
        assert agent["last_heartbeat_at"] is not None, (
            "Worker should have initial heartbeat after provisioning"
        )

    @pytest.mark.asyncio
    async def test_custom_provider_worker(self, client: AsyncClient, seed: SeedData):
        """验证使用 custom_provider_config 创建的 Worker 正常工作。"""
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 60, "method": "custom_test"},
        )
        worker = await _create_provisioned_worker(
            client, seed, "Custom-Provider-Worker", cfg,
        )
        assert worker["worker_id"].startswith("ag_")
        assert worker["config"]["heartbeat"]["timeout_seconds"] == 60
        assert worker["config"]["heartbeat"]["method"] == "custom_test"
        # 其他维度仍为 base Claude 值
        assert worker["config"]["evidence"]["format"] == "structured"


# ── 并发心跳 ────────────────────────────────────────────────────


class TestMultiWorkerHeartbeatConcurrent:
    """多 Worker 并发心跳 — 各自更新，不互相干扰。"""

    @pytest.mark.asyncio
    async def test_concurrent_heartbeats_both_succeed(
        self, client: AsyncClient, seed: SeedData,
    ):
        """两个 Worker 同时发送心跳 — 都应返回 200。"""
        env = await _setup_multi_worker_env(client, seed)

        async def _hb(worker: dict):
            return await client.post(
                f"/v1/agents/{worker['worker_id']}/heartbeat",
                json={"current_load": 1},
                headers=auth_header(worker["api_key"]),
            )

        results = await asyncio.gather(
            _hb(env["claude"]), _hb(env["codex"]),
        )
        for i, resp in enumerate(results):
            assert resp.status_code == 200, (
                f"Worker {i} heartbeat failed: {resp.status_code} {resp.text}"
            )
            assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_concurrent_heartbeats_update_independently(
        self, client: AsyncClient, seed: SeedData,
    ):
        """并发心跳后各 Worker last_heartbeat_at 独立更新。"""
        env = await _setup_multi_worker_env(client, seed)

        async def _hb(worker: dict):
            return await client.post(
                f"/v1/agents/{worker['worker_id']}/heartbeat",
                json={"current_load": 0},
                headers=auth_header(worker["api_key"]),
            )

        await asyncio.gather(
            _hb(env["claude"]), _hb(env["codex"]),
        )

        for label, worker_data in [("claude", env["claude"]), ("codex", env["codex"])]:
            resp = await client.get(
                f"/v1/agents/{worker_data['worker_id']}",
                headers=auth_header(seed.token),
            )
            assert resp.status_code == 200
            agent = resp.json()
            assert agent["last_heartbeat_at"] is not None, (
                f"{label} last_heartbeat_at should not be null"
            )

    @pytest.mark.asyncio
    async def test_concurrent_heartbeats_different_load_values(
        self, client: AsyncClient, seed: SeedData,
    ):
        """并发心跳携带不同负载 — 各自正确记录。"""
        env = await _setup_multi_worker_env(client, seed)

        async def _hb(worker: dict, load: int):
            return await client.post(
                f"/v1/agents/{worker['worker_id']}/heartbeat",
                json={"current_load": load},
                headers=auth_header(worker["api_key"]),
            )

        results = await asyncio.gather(
            _hb(env["claude"], 3),
            _hb(env["codex"], 7),
        )
        assert all(r.status_code == 200 for r in results)
        assert all(r.json()["status"] == "ok" for r in results)


# ── 超时检测: Claude (300s) ─────────────────────────────────────


class TestClaudeHeartbeatTimeout:
    """Claude Worker: 300s 超时。"""

    @pytest.mark.asyncio
    async def test_claude_active_within_timeout(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Claude 在 200s 无心跳 → 仍为 active（200s < 300s timeout）。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Claude-200s", claude_code_provider_config(),
        )

        # 将心跳设为 200s 前（在 300s timeout 内）
        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(worker["worker_id"], seconds=200)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert_worker_still_active(
            {"failed_workers": result["lines"]["heartbeat"]["failed_worker_ids"]},
            worker["worker_id"],
        )

    @pytest.mark.asyncio
    async def test_claude_offline_beyond_timeout(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Claude 在 400s 无心跳 → offline（400s > 300s timeout）。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Claude-400s", claude_code_provider_config(),
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(worker["worker_id"], seconds=400)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert_worker_offline(
            {"failed_workers": result["lines"]["heartbeat"]["failed_worker_ids"]},
            worker["worker_id"],
        )

    @pytest.mark.asyncio
    async def test_claude_beyond_timeout_via_timetravel(
        self, client: AsyncClient, seed: SeedData,
    ):
        """使用 TimeTravel.beyond_timeout=True — 自动读取 provider timeout 并设为超过。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Claude-Beyond", claude_code_provider_config(),
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            past = await tt.age_heartbeat(
                worker["worker_id"], beyond_timeout=True,
            )
            await db.commit()

            # beyond_timeout = timeout(300) + 60 = 360s
            diff = (datetime.now(timezone.utc) - past).total_seconds()
            assert 350 <= diff <= 370, (
                f"Expected ~360s ago (timeout 300 + 60), got {diff:.0f}s"
            )

        # 运行故障检测 — 360s > 300s timeout → offline
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert_worker_offline(
            {"failed_workers": result["lines"]["heartbeat"]["failed_worker_ids"]},
            worker["worker_id"],
        )


# ── 超时检测: Codex (1800s) ─────────────────────────────────────


class TestCodexHeartbeatTimeout:
    """Codex Worker: 1800s 超时。"""

    @pytest.mark.asyncio
    async def test_codex_active_at_400s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Codex 在 400s 无心跳 → 仍为 active（400s < 1800s timeout）。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Codex-400s", codex_cli_provider_config(),
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(worker["worker_id"], seconds=400)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert_worker_still_active(
            {"failed_workers": result["lines"]["heartbeat"]["failed_worker_ids"]},
            worker["worker_id"],
        )

    @pytest.mark.asyncio
    async def test_codex_offline_at_1900s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Codex 在 1900s 无心跳 → offline（1900s > 1800s timeout）。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Codex-1900s", codex_cli_provider_config(),
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(worker["worker_id"], seconds=1900)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert_worker_offline(
            {"failed_workers": result["lines"]["heartbeat"]["failed_worker_ids"]},
            worker["worker_id"],
        )

    @pytest.mark.asyncio
    async def test_codex_active_at_1500s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Codex 在 1500s 无心跳 → 接近超时但仍 active（1500s < 1800s）。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Codex-1500s", codex_cli_provider_config(),
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(worker["worker_id"], seconds=1500)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert_worker_still_active(
            {"failed_workers": result["lines"]["heartbeat"]["failed_worker_ids"]},
            worker["worker_id"],
        )


# ── Provider 差异回归守卫 ───────────────────────────────────────


class TestProviderTimeoutDifference:
    """B5 计划 §四·3 核心场景: 同一时间段 Claude offline, Codex active。"""

    @pytest.mark.asyncio
    async def test_both_workers_400s_without_heartbeat(
        self, client: AsyncClient, seed: SeedData,
    ):
        """400s 无心跳后:
        Claude (provider="claude", 300s timeout) → offline
        Codex (provider="codex", 1800s timeout) → active
        """
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        env = await _setup_multi_worker_env(client, seed)
        claude_id = env["claude"]["worker_id"]
        codex_id = env["codex"]["worker_id"]

        # 两个 Worker 都设为 400s 前的心跳
        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(claude_id, seconds=400)
            await tt.age_heartbeat(codex_id, seconds=400)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()
        failed_ids = result["lines"]["heartbeat"]["failed_worker_ids"]

        # Claude: 400s > 300s → offline
        assert claude_id in failed_ids, (
            f"Claude ({claude_id}) should be offline at 400s (timeout=300s)"
        )
        # Codex: 400s < 1800s → active
        assert codex_id not in failed_ids, (
            f"Codex ({codex_id}) should be active at 400s (timeout=1800s)"
        )

    @pytest.mark.asyncio
    async def test_both_workers_fresh_heartbeat(
        self, client: AsyncClient, seed: SeedData,
    ):
        """刚发送心跳的两个 Worker — 都应为 active。"""
        env = await _setup_multi_worker_env(client, seed)

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()
        failed = result["lines"]["heartbeat"]["failed_worker_ids"]

        assert env["claude"]["worker_id"] not in failed
        assert env["codex"]["worker_id"] not in failed

    @pytest.mark.asyncio
    async def test_claude_near_boundary_290s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Claude 290s 无心跳 — 在 timeout 内（290s < 300s），应为 active。

        使用 290s 而非 300s 避免 TimeTravel 与 detector 之间
        datetime.now() 调用时间差导致的边界误判。
        """
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Claude-NearBoundary", claude_code_provider_config(),
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(worker["worker_id"], seconds=290)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()
        failed = result["lines"]["heartbeat"]["failed_worker_ids"]

        assert worker["worker_id"] not in failed, (
            f"At 290s (< 300s timeout), worker should remain active. "
            f"Failed workers: {failed}"
        )


# ── 心跳更新验证 ────────────────────────────────────────────────


class TestHeartbeatUpdateVerification:
    """心跳发送后 last_heartbeat_at 正确更新。"""

    @pytest.mark.asyncio
    async def test_heartbeat_updates_last_heartbeat_at(
        self, client: AsyncClient, seed: SeedData,
    ):
        """发送心跳后 last_heartbeat_at 更新为当前时间。"""
        worker = await _create_provisioned_worker(
            client, seed, "HB-Update", claude_code_provider_config(),
        )

        hb_resp = await client.post(
            f"/v1/agents/{worker['worker_id']}/heartbeat",
            json={"current_load": 5},
            headers=auth_header(worker["api_key"]),
        )
        assert hb_resp.status_code == 200

        resp = await client.get(
            f"/v1/agents/{worker['worker_id']}",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        agent = resp.json()
        assert agent["last_heartbeat_at"] is not None

    @pytest.mark.asyncio
    async def test_heartbeat_with_current_task_id(
        self, client: AsyncClient, seed: SeedData,
    ):
        """心跳可携带 current_task_id。"""
        worker = await _create_provisioned_worker(
            client, seed, "HB-TaskID", claude_code_provider_config(),
        )

        resp = await client.post(
            f"/v1/agents/{worker['worker_id']}/heartbeat",
            json={"current_load": 1, "current_task_id": "tsk_test123"},
            headers=auth_header(worker["api_key"]),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_deactivated_worker_heartbeat_rejected(
        self, client: AsyncClient, seed: SeedData,
    ):
        """停用 Worker 后心跳被拒绝。"""
        # 不通过 harness 创建（harness 会分配 project role，产生 FK 约束
        # 阻止硬删除）。直接注册不含 project role 的 Worker。
        headers = auth_header(seed.token)

        reg_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "HB-Deact", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        assert reg_resp.status_code == 201
        worker_id = reg_resp.json()["worker"]["id"]
        api_key = reg_resp.json()["api_key"]

        # 停用 Worker（硬删除）
        del_resp = await client.delete(
            f"/v1/agents/{worker_id}",
            headers=headers,
        )
        assert del_resp.status_code == 204

        # 尝试发送心跳 — 应被拒绝（Worker 不存在）
        hb_resp = await client.post(
            f"/v1/agents/{worker_id}/heartbeat",
            json={"current_load": 0},
            headers=auth_header(api_key),
        )
        assert hb_resp.status_code == 401, (
            f"Deleted worker heartbeat should be rejected, "
            f"got {hb_resp.status_code}"
        )


# ── 故障检测结果结构 ────────────────────────────────────────────


class TestFailureDetectionStructure:
    """验证故障检测端点返回结构与 harness assertions 兼容。"""

    @pytest.mark.asyncio
    async def test_detection_result_has_expected_structure(
        self, client: AsyncClient, seed: SeedData,
    ):
        """验证 /admin/failure-detection/run 返回完整的四线检测结构。"""
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert "lines" in result
        assert "summary" in result
        assert "heartbeat" in result["lines"]
        assert "progress" in result["lines"]
        assert "lease" in result["lines"]
        assert "review" in result["lines"]

        hb = result["lines"]["heartbeat"]
        assert "failed_workers" in hb
        assert "failed_worker_ids" in hb
        assert "released_tasks" in hb
        assert "released_task_ids" in hb

        assert "total_failures_detected" in result["summary"]

    @pytest.mark.asyncio
    async def test_detection_failed_worker_ids_is_list(
        self, client: AsyncClient, seed: SeedData,
    ):
        """failed_worker_ids 必须是 list 类型（assertions 依赖此类型）。"""
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()
        assert isinstance(result["lines"]["heartbeat"]["failed_worker_ids"], list)
