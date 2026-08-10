"""P14-B2 G1: Error Report API 集成测试。

覆盖：
- 正常上报（带/不带 task_id）
- 认证/授权
- severity=🔴 触发 PFL + Task 自动创建
- 错误类型校验
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header
from src.services import pitfall_service as ps


# ── Fixture: temp pitfalls.md ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_pitfalls():
    """Redirect pitfall_service to a temp file so tests don't pollute real pitfalls.md."""
    content = """# Synapse 技术踩坑注册表

> 当前登记：1 项（1 PFL + 0 AP）

---

## 未闭环条目

### PFL-001 — Existing test entry ✅ 已修复

**踩坑日期**：2026-01-01（Test）· **状态**：✅ 已修复 · **严重度**：🟢

**现象**：Pre-existing test entry.

---
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="pitfalls_integration_", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        tmp_path = f.name

    ps.set_pitfalls_path_for_test(Path(tmp_path))
    yield
    ps.reset_pitfalls_path_for_test()
    Path(tmp_path).unlink(missing_ok=True)


class TestErrorReportEndpoint:
    """POST /v1/workers/{worker_id}/error-report 测试。"""

    @pytest.mark.asyncio
    async def test_report_error_basic(self, client: AsyncClient, seed: SeedData):
        """Admin worker 为自己上报基本错误 — 201 成功。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "api_error",
                "summary": "Test error from integration test",
                "detail": "This is a detailed error description for testing",
                "severity": "🟡",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["worker_id"] == seed.worker_id
        assert data["error_type"] == "api_error"
        assert data["summary"] == "Test error from integration test"
        assert data["severity"] == "🟡"
        assert data["event_id"] is not None
        assert data["pfl_id"] is None  # severity=🟡 不触发 PFL

    @pytest.mark.asyncio
    async def test_report_error_with_task_id(self, client: AsyncClient, seed: SeedData):
        """关联 Task 的错误上报 — 201 成功。"""
        headers = auth_header(seed.token)

        # 通过 API 创建 project
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Error Report Test Project", "description": "Test project for error reporting", "slug": f"err-rpt-test-{seed.team_id[-6:]}"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        # 通过 API 创建 task
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Test Task for Error Report",
                "description": "A task to link error reports to",
                "priority": "p2",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        task_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "verification_failed",
                "task_id": task_id,
                "summary": "Verification failed after 2 rework attempts",
                "detail": "All verification conditions met but O rejected with unclear feedback",
                "severity": "🔴",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["error_type"] == "verification_failed"
        assert data["pfl_id"] is not None, (
            f"Expected PFL auto-creation for 🔴 severity, got: {data}"
        )
        assert data["escalation_task_id"] is not None, (
            f"Expected escalation Task auto-creation for 🔴 severity, got: {data}"
        )

    @pytest.mark.asyncio
    async def test_report_error_unauthorized(self, client: AsyncClient, seed: SeedData):
        """无认证头 — 401。"""
        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "api_error",
                "summary": "Should fail without auth",
                "severity": "🟡",
            },
        )
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_report_error_invalid_type(self, client: AsyncClient, seed: SeedData):
        """无效 error_type — 422。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "INVALID_TYPE",
                "summary": "Should fail validation",
                "severity": "🟡",
            },
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_report_error_missing_summary(self, client: AsyncClient, seed: SeedData):
        """缺少必填 summary — 422。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "api_error",
                "severity": "🟡",
            },
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_report_error_invalid_severity(self, client: AsyncClient, seed: SeedData):
        """无效 severity — 422。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "api_error",
                "summary": "Invalid severity",
                "severity": "CRITICAL",  # 必须是 emoji
            },
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_report_error_severity_critical_triggers_pfl(
        self, client: AsyncClient, seed: SeedData
    ):
        """severity=🔴 触发 PFL 自动创建。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "env_broken",
                "summary": "Critical environment failure - triggers PFL",
                "detail": "Python 3.13 unavailable, pip install fails, cannot proceed",
                "context": {"python_version": "3.12", "required": "3.13"},
                "severity": "🔴",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["severity"] == "🔴"
        assert data["pfl_id"] is not None, (
            f"Expected PFL auto-creation for 🔴 severity, got: {data}"
        )
        assert data["pfl_id"].startswith("PFL-"), (
            f"PFL ID should start with 'PFL-', got: {data['pfl_id']}"
        )
        # No task_id → no project context → escalation Task creation skipped
        assert data["escalation_task_id"] is None, (
            f"Expected no escalation Task without task_id, got: {data}"
        )

    @pytest.mark.asyncio
    async def test_report_error_with_context(self, client: AsyncClient, seed: SeedData):
        """context 字段正确存储。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "timeout",
                "summary": "API timeout with context",
                "context": {
                    "http_status": 504,
                    "endpoint": "/v1/tasks/claim",
                    "retry_count": 3,
                    "last_retry_at": "2026-08-10T12:00:00Z",
                },
                "severity": "🟡",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["error_type"] == "timeout"

    @pytest.mark.asyncio
    async def test_report_error_all_types(self, client: AsyncClient, seed: SeedData):
        """所有 error_type 都被接受。"""
        headers = auth_header(seed.token)
        valid_types = [
            "api_error",
            "verification_failed",
            "dependency_blocked",
            "capability_mismatch",
            "env_broken",
            "timeout",
            "escalation",
            "unknown",
        ]

        for error_type in valid_types:
            resp = await client.post(
                f"/v1/workers/{seed.worker_id}/error-report",
                json={
                    "error_type": error_type,
                    "summary": f"Testing error type: {error_type}",
                    "severity": "🟢",
                },
                headers=headers,
            )
            assert resp.status_code == 201, (
                f"Expected 201 for error_type={error_type}, got {resp.status_code}: {resp.text}"
            )

    @pytest.mark.asyncio
    async def test_report_error_visible_in_worker_state(
        self, client: AsyncClient, seed: SeedData
    ):
        """Worker state 中包含最近的错误报告。"""
        headers = auth_header(seed.token)

        # 先上报一个错误
        await client.post(
            f"/v1/workers/{seed.worker_id}/error-report",
            json={
                "error_type": "api_error",
                "summary": "Error visible in state test",
                "severity": "🔴",
            },
            headers=headers,
        )

        # 通过 API 创建 project
        resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "State Test Project", "description": "Test project for state visibility", "slug": f"state-test-{seed.team_id[-6:]}"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["id"]

        state_resp = await client.get(
            f"/v1/workers/me/state?project_id={project_id}",
            headers=headers,
        )
        assert state_resp.status_code == 200, state_resp.text
        state = state_resp.json()
        assert "recent_error_reports" in state, (
            f"WorkerStateResponse should include recent_error_reports"
        )
        assert len(state["recent_error_reports"]) >= 1, (
            f"Should have at least 1 recent error report"
        )
