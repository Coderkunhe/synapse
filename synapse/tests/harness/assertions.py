"""专用测试断言。

P13-B6: 覆盖时序窗口、并发结果、Provider 差异场景。
所有断言函数遵循 pytest 风格 — 断言失败时给出可读的错误消息。

用法:
    from tests.harness.assertions import (
        assert_within_window, assert_worker_offline, assert_task_released,
    )
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from httpx import AsyncClient

from tests.conftest import auth_header


# ── 时序断言 ──────────────────────────────────────────────────

def assert_within_window(
    actual: datetime,
    expected_window_start: datetime,
    tolerance_seconds: float = 5.0,
) -> None:
    """断言时间戳在预期窗口内。

    Args:
        actual: 实际时间戳（通常是 now() 或刚刚生成的时间）。
        expected_window_start: 窗口起始时间。
        tolerance_seconds: 允许偏差（默认 5s）。
    """
    diff = (actual - expected_window_start).total_seconds()
    assert 0 <= diff <= tolerance_seconds, (
        f"Expected timestamp within [{expected_window_start}, "
        f"+{tolerance_seconds}s], got diff={diff:.1f}s"
    )


# ── Worker 状态断言 ───────────────────────────────────────────

def assert_worker_offline(
    detector_result: dict,
    worker_id: str,
) -> None:
    """断言 Worker 被故障检测器判定为 offline。"""
    failed = detector_result.get("failed_workers", [])
    assert worker_id in failed, (
        f"Worker {worker_id} should be offline, "
        f"but only {failed} are marked failed"
    )


def assert_worker_still_active(
    detector_result: dict,
    worker_id: str,
) -> None:
    """断言 Worker 未被故障检测器判定为 offline。"""
    failed = detector_result.get("failed_workers", [])
    assert worker_id not in failed, (
        f"Worker {worker_id} should still be active, "
        f"but is in failed list: {failed}"
    )


# ── Task 状态断言 ─────────────────────────────────────────────

def assert_task_released(task_response: dict) -> None:
    """断言任务已释放回 READY（owner 清空）。"""
    assert task_response["status"] == "ready", (
        f"Expected task status 'ready', got '{task_response.get('status')}'"
    )
    assert task_response["owner_id"] is None, (
        f"Expected owner_id None, got '{task_response.get('owner_id')}'"
    )
    assert task_response["owner_type"] is None, (
        f"Expected owner_type None, got '{task_response.get('owner_type')}'"
    )


def assert_task_still_owned(task_response: dict, expected_owner_id: str) -> None:
    """断言任务仍归指定 Worker。"""
    assert task_response["status"] == "in_progress", (
        f"Expected task status 'in_progress', got '{task_response.get('status')}'"
    )
    assert task_response["owner_id"] == expected_owner_id, (
        f"Expected owner_id '{expected_owner_id}', got '{task_response.get('owner_id')}'"
    )


# ── 并发操作 ──────────────────────────────────────────────────

async def concurrent_claim(
    client: AsyncClient,
    task_id: str,
    workers: list[dict],
    expected_version: int,
) -> dict:
    """多个 Worker 同时 claim 同一个 task。

    使用 asyncio.gather 并发发送请求（D-P13-009）。
    恰好一个 Worker 成功（200），其余遇到冲突（409）。

    Args:
        client: ASGI 测试客户端。
        task_id: 目标 Task ID。
        workers: Worker dict 列表（每个含 api_key）。
        expected_version: 乐观锁版本号。

    Returns:
        {
            "success": worker_index | None,
            "conflicts": [worker_index, ...],
            "results": [response_dict | error_text, ...],
        }
    """

    async def _claim(worker: dict):
        resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            json={"expected_version": expected_version},
            headers=auth_header(worker["api_key"]),
        )
        return resp

    # 并发执行所有 claim
    results = await asyncio.gather(*[_claim(w) for w in workers])

    success = None
    conflicts = []
    for i, resp in enumerate(results):
        if resp.status_code == 200:
            success = i
        elif resp.status_code == 409:
            conflicts.append(i)

    return {
        "success": success,
        "conflicts": conflicts,
        "results": [
            r.json() if r.status_code == 200 else r.text for r in results
        ],
    }
