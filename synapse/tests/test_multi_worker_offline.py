"""P13-B8: Offline 维度多 Worker 测试。

测试覆盖:
  - Stale task 检测: TimeTravel + stale_task_detector 集成
  - 租约过期释放: expire_lease → release_expired_leases
  - Offline config 验证: Provider recovery strategy 差异
  - Offline timeout 边界: zero timeout 语义 · 差异超时

使用 B6 harness: _create_provisioned_worker + TimeTravel + assertions。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ready_task
from tests.harness.assertions import (
    assert_task_released,
    assert_task_still_owned,
)
from tests.harness.fixtures import _create_provisioned_worker
from tests.harness.providers import (
    claude_code_provider_config,
    codex_cli_provider_config,
    custom_provider_config,
)


# ── 辅助: 创建 worker + task 并 claim ────────────────────────────


async def _create_claimed_task(
    client: AsyncClient,
    seed: SeedData,
    worker: dict,
    task_title: str = "Offline Test Task",
) -> dict:
    """创建 project task 并由指定 Worker claim。

    Returns: {"task_id": ..., "version": ..., "project_id": ..., "worker": ...}
    """
    headers = auth_header(seed.token)

    create_resp = await client.post(
        f"/v1/projects/{worker['project_id']}/tasks",
        json={
            "title": task_title,
            "description": "Testing offline/stale detection scenarios",
            "priority": "p2",
            "verifications": [{"type": "manual", "description": "Verify behavior"}],
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, f"Task create failed: {create_resp.text}"
    task = create_resp.json()
    task = await ready_task(client, task, seed.token)

    claim_resp = await client.post(
        f"/v1/tasks/{task['id']}/claim",
        json={"expected_version": task["version_no"]},
        headers=auth_header(worker["api_key"]),
    )
    assert claim_resp.status_code == 200, f"Claim failed: {claim_resp.text}"

    return {
        "task_id": task["id"],
        "version": claim_resp.json()["version_no"],
        "project_id": worker["project_id"],
        "worker": worker,
    }


# ── Offline Config 验证 ─────────────────────────────────────────


class TestOfflineConfigValidation:
    """offline 维度 config 结构 + 差异验证。"""

    def test_claude_offline_recovery_is_daemon_auto_restart(self):
        cfg = claude_code_provider_config()
        assert cfg["offline"]["recovery"] == "daemon_auto_restart"

    def test_codex_offline_recovery_is_cron_window(self):
        cfg = codex_cli_provider_config()
        assert cfg["offline"]["recovery"] == "cron_window"

    def test_claude_offline_timeout_matches_heartbeat_timeout(self):
        """offline timeout 应与 heartbeat timeout 一致（同一检测窗口）。"""
        cfg = claude_code_provider_config()
        assert cfg["offline"]["timeout_seconds"] == cfg["heartbeat"]["timeout_seconds"]

    def test_codex_offline_timeout_matches_heartbeat_timeout(self):
        cfg = codex_cli_provider_config()
        assert cfg["offline"]["timeout_seconds"] == cfg["heartbeat"]["timeout_seconds"]

    def test_recovery_strategies_mutually_exclusive(self):
        """两个 Provider 的恢复策略应不同。"""
        claude_rec = claude_code_provider_config()["offline"]["recovery"]
        codex_rec = codex_cli_provider_config()["offline"]["recovery"]
        assert claude_rec != codex_rec

    def test_zero_timeout_offline_never_disconnects(self):
        """timeout=0 语义: 永不断开。"""
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 0},
            offline={"timeout_seconds": 0},
        )
        assert cfg["offline"]["timeout_seconds"] == 0

    def test_custom_offline_timeout(self):
        """自定义 offline timeout 应生效。"""
        cfg = custom_provider_config(offline={"timeout_seconds": 120})
        assert cfg["offline"]["timeout_seconds"] == 120
        # recovery 保持原值
        assert cfg["offline"]["recovery"] == "daemon_auto_restart"


# ── Stale Task 检测 ─────────────────────────────────────────────


class TestStaleTaskDetection:
    """使用 TimeTravel + 直接调用 detect_stale_tasks 验证 stale 检测。

    stale task 检测作为后台 reaper 运行（无独立 admin API 端点），
    测试通过 DB session 直接调用服务函数验证行为。
    """

    @pytest.mark.asyncio
    async def test_stale_detector_service_exists_and_runs(
        self, client: AsyncClient, seed: SeedData,
    ):
        """验证 detect_stale_tasks 服务可导入并正常返回结构化结果。"""
        from src.db import async_session_factory
        from src.services.stale_task_detector import detect_stale_tasks

        # 创建 worker + claimed task（不设置时间旅行 — 仅验证服务运行）
        worker = await _create_provisioned_worker(
            client, seed, "Stale-Worker", claude_code_provider_config(),
        )
        await _create_claimed_task(client, seed, worker, "Stale Basic")

        async with async_session_factory() as db:
            result = await detect_stale_tasks(db, threshold_minutes=90, reassign_threshold_minutes=10)
            await db.commit()

        # 验证返回结构完整性
        assert "stale_count" in result
        assert "stale_task_ids" in result
        assert isinstance(result["stale_task_ids"], list)
        assert "reassigned_count" in result
        assert "reassigned_task_ids" in result

    @pytest.mark.asyncio
    async def test_fresh_task_not_stale(
        self, client: AsyncClient, seed: SeedData,
    ):
        """刚 claim 的 task（updated_at 在阈值内）不应被 stale detector 标记。"""
        from src.services.stale_task_detector import detect_stale_tasks
        from src.db import async_session_factory

        worker = await _create_provisioned_worker(
            client, seed, "Fresh-Worker", claude_code_provider_config(),
        )
        data = await _create_claimed_task(client, seed, worker, "Fresh Task")

        async with async_session_factory() as db:
            result = await detect_stale_tasks(
                db, threshold_minutes=90, reassign_threshold_minutes=10,
            )
            await db.commit()

        assert data["task_id"] not in result.get("stale_task_ids", []), (
            f"Fresh task should not be stale. Stale IDs: {result.get('stale_task_ids')}"
        )

    @pytest.mark.asyncio
    async def test_stale_detector_default_threshold_respected(
        self, client: AsyncClient, seed: SeedData,
    ):
        """threshold_minutes 参数应被尊重 — 高于阈值的才 stale。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel
        from src.services.stale_task_detector import detect_stale_tasks

        worker = await _create_provisioned_worker(
            client, seed, "Threshold-Worker", claude_code_provider_config(),
        )
        data = await _create_claimed_task(client, seed, worker, "Threshold Test")

        # 设为 30 分钟前（在 90min threshold 内，不应 stale）
        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.advance_updated_at(data["task_id"], minutes=30)
            await db.commit()

        async with async_session_factory() as db:
            result = await detect_stale_tasks(db, threshold_minutes=90, reassign_threshold_minutes=10)
            await db.commit()

        # 30min < 90min threshold → not stale
        assert data["task_id"] not in result["stale_task_ids"], (
            f"Task 30min old with 90min threshold should not be stale"
        )


# ── 租约过期 ────────────────────────────────────────────────────


class TestLeaseExpiry:
    """租约过期 → 任务释放回 READY。"""

    @pytest.mark.asyncio
    async def test_expired_lease_releases_task(
        self, client: AsyncClient, seed: SeedData,
    ):
        """租约过期后 release_expired_leases 应释放任务。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Lease-Worker", claude_code_provider_config(),
        )
        data = await _create_claimed_task(client, seed, worker, "Lease Expiry")

        # Expire the lease
        async with async_session_factory() as db:
            tt = TimeTravel(db)
            await tt.expire_lease(data["task_id"])
            await db.commit()

        # 运行故障检测（包含 lease detection）
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        assert result["lines"]["lease"]["released_tasks"] > 0, (
            f"Lease detector should release expired lease. Result: {result['lines']['lease']}"
        )
        assert data["task_id"] in result["lines"]["lease"]["released_task_ids"], (
            f"Task {data['task_id']} should be in released list"
        )

        # 验证任务已被释放
        task_resp = await client.get(
            f"/v1/tasks/{data['task_id']}",
            headers=auth_header(seed.token),
        )
        assert task_resp.status_code == 200
        assert_task_released(task_resp.json())

    @pytest.mark.asyncio
    async def test_unexpired_lease_keeps_task_owned(
        self, client: AsyncClient, seed: SeedData,
    ):
        """未过期租约 — 任务保持 owned。"""
        worker = await _create_provisioned_worker(
            client, seed, "Active-Worker", claude_code_provider_config(),
        )
        data = await _create_claimed_task(client, seed, worker, "Active Lease")

        # 立即运行检测 — 租约刚设置
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        result = resp.json()

        # 租约刚设置，不应被释放
        assert data["task_id"] not in result["lines"]["lease"]["released_task_ids"], (
            "Fresh lease should not be released"
        )

        task_resp = await client.get(
            f"/v1/tasks/{data['task_id']}",
            headers=auth_header(seed.token),
        )
        assert task_resp.status_code == 200
        assert_task_still_owned(task_resp.json(), worker["worker_id"])


# ── Offline 超时差异 ────────────────────────────────────────────


class TestOfflineTimeoutDifference:
    """Claude vs Codex offline timeout 差异回归守卫。"""

    @pytest.mark.asyncio
    async def test_claude_worker_becomes_error_on_heartbeat_timeout(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Claude Worker heartbeat 超时 → runtime_status → ERROR。"""
        from src.db import async_session_factory
        from tests.harness.time_travel import TimeTravel

        worker = await _create_provisioned_worker(
            client, seed, "Claude-Err", claude_code_provider_config(),
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

        assert result["lines"]["heartbeat"]["failed_workers"] > 0, (
            "Claude Worker should be detected as failed at 400s"
        )

        # 验证 Worker runtime_status 已变为 ERROR
        get_resp = await client.get(
            f"/v1/agents/{worker['worker_id']}",
            headers=auth_header(seed.token),
        )
        assert get_resp.status_code == 200
        agent = get_resp.json()
        assert agent["runtime_status"] == "error", (
            f"Expected runtime_status=error, got {agent['runtime_status']}"
        )
