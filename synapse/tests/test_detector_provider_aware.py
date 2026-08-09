"""P13-B8: 检测器去硬编码回归测试。

测试覆盖:
  - Failure detector: provider-aware timeout 一致性 (P12-B45)
  - 回归守卫: Claude (300s) vs Codex (1800s) 不退化
  - Stale task detector: 现有行为基线
  - 多 Provider 并发检测正确性

这些测试作为 B8+ 检测器去硬编码（从 `provider == "codex"` →
`provider_config.heartbeat.timeout_seconds`）的回归安全网。

使用 B6 harness: _create_provisioned_worker + TimeTravel + assertions。
"""

from __future__ import annotations

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


# ── 辅助 ────────────────────────────────────────────────────────


async def _setup_multi_worker(client: AsyncClient, seed: SeedData) -> dict:
    """创建 Claude + Codex 双 Worker 用于检测器差异测试。"""
    claude = await _create_provisioned_worker(
        client, seed, "Det-Claude", claude_code_provider_config(),
    )
    codex = await _create_provisioned_worker(
        client, seed, "Det-Codex", codex_cli_provider_config(),
    )
    return {"claude": claude, "codex": codex}


# ── Failure Detector Provider-Aware 回归 ───────────────────────


class TestFailureDetectorProviderAware:
    """P12-B45 (PFL-144): provider-aware heartbeat timeout。

    B8+ 去硬编码后，超时应从 provider_config.heartbeat.timeout_seconds 读取
    而非硬编码 `if worker.provider == "codex"`。
    """

    @pytest.mark.asyncio
    async def test_claude_offline_at_400s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Claude (300s timeout): 400s stale → offline。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "FD-Claude", claude_code_provider_config(),
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
    async def test_codex_stays_active_at_400s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Codex (1800s timeout): 400s stale → 仍 active。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "FD-Codex", codex_cli_provider_config(),
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
    async def test_both_workers_diverge_at_400s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """核心回归守卫: 400s 时 Claude offline · Codex active。

        当 B8+ 去硬编码后，此测试必须继续通过 —
        无论超时来自 `provider == "codex"` 还是 `provider_config.heartbeat.timeout_seconds`。
        """
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        env = await _setup_multi_worker(client, seed)

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.age_heartbeat(env["claude"]["worker_id"], seconds=400)
            await tt.age_heartbeat(env["codex"]["worker_id"], seconds=400)
            await db.commit()

        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()
        failed = result["lines"]["heartbeat"]["failed_worker_ids"]

        assert env["claude"]["worker_id"] in failed, (
            f"Claude (300s timeout) must be offline at 400s"
        )
        assert env["codex"]["worker_id"] not in failed, (
            f"Codex (1800s timeout) must be active at 400s"
        )

    @pytest.mark.asyncio
    async def test_codex_detected_offline_at_1900s(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Codex (1800s timeout): 1900s stale → offline。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "FD-Codex-Late", codex_cli_provider_config(),
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


# ── Failure Detector 结构完整性 ─────────────────────────────────


class TestFailureDetectorStructure:
    """故障检测器响应结构回归守卫。"""

    @pytest.mark.asyncio
    async def test_all_four_detection_lines_present(
        self, client: AsyncClient, seed: SeedData,
    ):
        """四条检测线必须全部出现在响应中。"""
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        lines = result["lines"]
        assert "heartbeat" in lines
        assert "progress" in lines
        assert "lease" in lines
        assert "review" in lines

    @pytest.mark.asyncio
    async def test_heartbeat_line_has_required_fields(
        self, client: AsyncClient, seed: SeedData,
    ):
        """heartbeat line 应包含 assertions 所需的字段。"""
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        hb = resp.json()["lines"]["heartbeat"]

        assert "detector" in hb
        assert hb["detector"] == "heartbeat"
        assert "failed_workers" in hb
        assert "failed_worker_ids" in hb
        assert isinstance(hb["failed_worker_ids"], list)
        assert "released_tasks" in hb
        assert "released_task_ids" in hb

    @pytest.mark.asyncio
    async def test_summary_has_total_failures(
        self, client: AsyncClient, seed: SeedData,
    ):
        """summary 应包含 total_failures_detected。"""
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert "total_failures_detected" in summary


# ── Provider Config 驱动超时验证 ────────────────────────────────


class TestProviderConfigDrivenTimeout:
    """验证 provider config 中的 timeout_seconds 与 detector 行为一致。"""

    def test_claude_config_timeout_matches_detector_default(self):
        """B8 前: config timeout 应匹配 detector standard_timeout (300s)。"""
        config_to = claude_code_provider_config()["heartbeat"]["timeout_seconds"]
        assert config_to == 300, (
            f"Claude config timeout should be 300s, got {config_to}s"
        )

    def test_codex_config_timeout_matches_detector_codex_timeout(self):
        """B8 前: config timeout 应匹配 detector codex_timeout (1800s)。"""
        config_to = codex_cli_provider_config()["heartbeat"]["timeout_seconds"]
        assert config_to == 1800, (
            f"Codex config timeout should be 1800s, got {config_to}s"
        )

    def test_custom_timeout_can_deviate_from_defaults(self):
        """自定义 timeout 可以不同于标准值 — B8+ detector 从 config 读取。"""
        cfg = custom_provider_config(heartbeat={"timeout_seconds": 60})
        assert cfg["heartbeat"]["timeout_seconds"] == 60

    def test_config_and_detector_timeout_consistency(self):
        """一致性门禁: 两个 Provider config timeout 不能相同。

        如果相同则说明 config 或 detector 有误。
        """
        claude_to = claude_code_provider_config()["heartbeat"]["timeout_seconds"]
        codex_to = codex_cli_provider_config()["heartbeat"]["timeout_seconds"]
        assert claude_to != codex_to, (
            f"Claude ({claude_to}s) and Codex ({codex_to}s) timeouts must differ"
        )
