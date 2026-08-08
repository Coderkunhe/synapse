"""P13-B6: Harness 工具库 smoke test。

验证 tests/harness/ 五文件在真实 ASGI 测试环境中可用。
这是 B5 设计文档 §二 要求的 L3 集成验证 — 不是完整测试套件，
而是证明 harness 架构可工作。

完整五维测试矩阵在 B7+ 分批实现。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData
from tests.harness.providers import (
    claude_code_provider_config,
    codex_cli_provider_config,
    custom_provider_config,
)


class TestHarnessProviders:
    """L2: Provider 配置工厂 — 纯数据测试（无 DB 依赖）。"""

    def test_claude_config_structure(self):
        cfg = claude_code_provider_config()
        assert cfg["type"] == "claude_code"
        assert cfg["heartbeat"]["timeout_seconds"] == 300
        assert cfg["heartbeat"]["method"] == "daemon"
        assert cfg["evidence"]["format"] == "structured"
        assert cfg["state"]["primary_source"] == "file"

    def test_codex_config_structure(self):
        cfg = codex_cli_provider_config()
        assert cfg["type"] == "codex_cli"
        assert cfg["heartbeat"]["timeout_seconds"] == 1800
        assert cfg["heartbeat"]["method"] == "cron"
        assert cfg["evidence"]["format"] == "free_text"
        assert cfg["state"]["primary_source"] == "api"

    def test_provider_timeout_difference(self):
        """核心差异: Claude 300s vs Codex 1800s timeout。"""
        claude = claude_code_provider_config()
        codex = codex_cli_provider_config()
        assert claude["heartbeat"]["timeout_seconds"] < codex["heartbeat"]["timeout_seconds"]

    def test_custom_provider_config_overrides(self):
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 10},
            offline={"timeout_seconds": 10},
        )
        assert cfg["heartbeat"]["timeout_seconds"] == 10
        assert cfg["offline"]["timeout_seconds"] == 10
        # 其他字段不变
        assert cfg["type"] == "claude_code"
        assert cfg["evidence"]["format"] == "structured"

    def test_custom_provider_config_zero_timeout(self):
        """零超时语义: 永不断开。"""
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 0},
            offline={"timeout_seconds": 0},
        )
        assert cfg["heartbeat"]["timeout_seconds"] == 0
        assert cfg["offline"]["timeout_seconds"] == 0

    def test_all_provider_configs_have_five_dimensions(self):
        """每个 Provider config 必须覆盖 B4 五维契约。"""
        for cfg in [claude_code_provider_config(), codex_cli_provider_config()]:
            assert "heartbeat" in cfg
            assert "offline" in cfg
            assert "evidence" in cfg
            assert "state" in cfg
            assert "startup" in cfg


    def test_custom_provider_config_rejects_non_dict(self):
        """非 dict 覆盖值应抛出清晰的 TypeError。"""
        import pytest
        with pytest.raises(TypeError, match="expects a dict"):
            custom_provider_config(heartbeat="not_a_dict")


class TestHarnessFixtures:
    """L3: Provider-aware fixtures — 需要 ASGI + DB。"""

    @pytest.mark.asyncio
    async def test_claude_worker_fixture(self, client: AsyncClient, seed: SeedData):
        """验证 Claude Worker fixture 完整生命周期。"""
        from tests.harness.fixtures import _create_provisioned_worker

        worker = await _create_provisioned_worker(
            client, seed, "SmokeTest-Claude", claude_code_provider_config()
        )
        assert worker["worker_id"].startswith("ag_")
        assert len(worker["api_key"]) > 20
        assert worker["project_id"] is not None
        assert worker["config"]["type"] == "claude_code"

    @pytest.mark.asyncio
    async def test_codex_worker_fixture(self, client: AsyncClient, seed: SeedData):
        """验证 Codex Worker fixture 完整生命周期。"""
        from tests.harness.fixtures import _create_provisioned_worker

        worker = await _create_provisioned_worker(
            client, seed, "SmokeTest-Codex", codex_cli_provider_config()
        )
        assert worker["worker_id"].startswith("ag_")
        assert len(worker["api_key"]) > 20
        assert worker["config"]["type"] == "codex_cli"

    @pytest.mark.asyncio
    async def test_multi_worker_env_isolation(self, client: AsyncClient, seed: SeedData):
        """双 Worker 环境各自独立 project（隔离性原则）。"""
        from tests.harness.fixtures import _create_provisioned_worker

        claude = await _create_provisioned_worker(
            client, seed, "Claude-Iso", claude_code_provider_config()
        )
        codex = await _create_provisioned_worker(
            client, seed, "Codex-Iso", codex_cli_provider_config()
        )
        # 不同 project
        assert claude["project_id"] != codex["project_id"]
        # 不同 worker
        assert claude["worker_id"] != codex["worker_id"]
        # 各自有独立 api_key
        assert claude["api_key"] != codex["api_key"]


class TestHarnessTimeTravel:
    """L1: TimeTravel 工具 — 需要 DB session。"""

    @pytest.mark.asyncio
    async def test_age_heartbeat_with_seconds(self, client: AsyncClient, seed: SeedData):
        """验证 age_heartbeat 正确回退 last_heartbeat_at。"""
        from datetime import datetime, timezone
        from src.db import async_session_factory
        from src.models.worker import Worker
        from tests.harness.time_travel import TimeTravel

        # 先创建一个 worker
        from tests.harness.fixtures import _create_provisioned_worker
        worker_data = await _create_provisioned_worker(
            client, seed, "TT-Test", claude_code_provider_config()
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            past = await tt.age_heartbeat(worker_data["worker_id"], seconds=120)

            # 验证 age_heartbeat 返回的过去时间戳（aware）
            diff = (datetime.now(timezone.utc) - past).total_seconds()
            assert 110 <= diff <= 130, f"Expected ~120s ago, got {diff:.0f}s"

            # 验证 DB 中的值也已更新（SQLite 不保留时区）
            worker = await db.get(Worker, worker_data["worker_id"])
            assert worker is not None
            assert worker.last_heartbeat_at is not None

    @pytest.mark.asyncio
    async def test_age_heartbeat_beyond_timeout(self, client: AsyncClient, seed: SeedData):
        """验证 beyond_timeout=True 使用 provider 配置的 timeout。"""
        from datetime import datetime, timezone
        from src.db import async_session_factory
        from src.models.worker import Worker
        from tests.harness.time_travel import TimeTravel

        from tests.harness.fixtures import _create_provisioned_worker
        worker_data = await _create_provisioned_worker(
            client, seed, "TT-Timeout", claude_code_provider_config()
        )

        async with async_session_factory() as db:
            tt = TimeTravel(db)
            past = await tt.age_heartbeat(worker_data["worker_id"], beyond_timeout=True)

            # Claude default timeout = 300s, beyond_timeout = 300 + 60 = 360s
            diff = (datetime.now(timezone.utc) - past).total_seconds()
            assert 350 <= diff <= 370, f"Expected ~360s ago, got {diff:.0f}s"

            worker = await db.get(Worker, worker_data["worker_id"])
            assert worker is not None
            assert worker.last_heartbeat_at is not None

    @pytest.mark.asyncio
    async def test_expire_lease(self, client: AsyncClient, seed: SeedData):
        """验证 expire_lease 将 lease_expires_at 设为过去。"""
        from datetime import datetime, timezone
        from src.db import async_session_factory
        from src.models.task import Task
        from tests.harness.time_travel import TimeTravel
        from tests.conftest import auth_header

        # 创建 task 并 claim
        from tests.harness.fixtures import _create_provisioned_worker
        worker_data = await _create_provisioned_worker(
            client, seed, "TT-Lease", claude_code_provider_config()
        )

        # 创建 + ready task
        create_resp = await client.post(
            f"/v1/projects/{worker_data['project_id']}/tasks",
            json={"title": "Lease Test", "description": "Testing lease expiry"},
            headers=auth_header(seed.token),
        )
        assert create_resp.status_code == 201
        task_id = create_resp.json()["id"]

        from tests.conftest import ready_task
        task = create_resp.json()
        task = await ready_task(client, task, seed.token)

        # Claim
        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            json={"expected_version": task["version_no"]},
            headers=auth_header(worker_data["api_key"]),
        )
        assert claim_resp.status_code == 200

        # Expire lease
        async with async_session_factory() as db:
            tt = TimeTravel(db)
            past = await tt.expire_lease(task_id)

            # 验证返回的过去时间戳
            diff = (datetime.now(timezone.utc) - past).total_seconds()
            assert 0 <= diff <= 5, f"Expected lease expired ~1s ago, got {diff:.0f}s"

            task_obj = await db.get(Task, task_id)
            assert task_obj is not None
            assert task_obj.lease_expires_at is not None


class TestHarnessAssertions:
    """L1: 专用断言 — 纯函数测试（无 DB 依赖）。"""

    def test_assert_within_window_pass(self):
        from datetime import datetime, timedelta, timezone
        from tests.harness.assertions import assert_within_window

        now = datetime.now(timezone.utc)
        actual = now + timedelta(seconds=2)
        assert_within_window(actual, now, tolerance_seconds=5.0)

    def test_assert_worker_offline(self):
        from tests.harness.assertions import assert_worker_offline
        result = {"failed_workers": ["ag_001", "ag_002"]}
        assert_worker_offline(result, "ag_001")

    def test_assert_worker_still_active(self):
        from tests.harness.assertions import assert_worker_still_active
        result = {"failed_workers": ["ag_002"]}
        assert_worker_still_active(result, "ag_001")

    def test_assert_task_released(self):
        from tests.harness.assertions import assert_task_released
        task = {"status": "ready", "owner_id": None, "owner_type": None}
        assert_task_released(task)

    def test_assert_task_still_owned(self):
        from tests.harness.assertions import assert_task_still_owned
        task = {"status": "in_progress", "owner_id": "ag_001"}
        assert_task_still_owned(task, "ag_001")
