"""P8-B9：review.overdue 信号 — failure_detector 对过期审查发出逾期事件。

测试覆盖 B9 补救中引入的第 8 种 WS 信号类型：
  - EventType.REVIEW_OVERDUE 枚举存在性
  - failure_detector 的 detect_review_timeouts 发出 review.overdue 事件
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.db import async_session_factory
from src.models.event import Event
from src.models.verification import Verification
from tests.conftest import SeedData, auth_header, ready_task


# ── 辅助函数 ──────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, seed: SeedData, slug: str = "") -> dict:
    import uuid

    s = slug or f"b9-ro-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": "B9 RO Test Project", "description": "test", "slug": s},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_task(
    client: AsyncClient, seed: SeedData, project_id: str,
    title: str = "Test Task",
) -> dict:
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={
            "title": title,
            "description": "Test description",
            "priority": "p2",
            "verifications": [{"type": "manual", "description": "Check output"}],
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201
    return resp.json()


async def _get_events(client: AsyncClient, seed: SeedData) -> list[dict]:
    resp = await client.get(
        f"/v1/teams/{seed.team_id}/events",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    return resp.json()["items"]


# ── 审查逾期信号 ──────────────────────────────────────────────────────


class TestReviewOverdueSignal:
    """review.overdue 事件发射（P8-B9，第 8 种 WS 信号类型）。"""

    async def test_review_overdue_event_exists_in_enum(self):
        """EventType.REVIEW_OVERDUE 已定义。"""
        from src.constants import EventType

        assert EventType.REVIEW_OVERDUE == "review.overdue"

    async def test_review_overdue_emitted_for_stale_task(
        self, client: AsyncClient, seed: SeedData,
    ):
        """failure_detector 对滞留验证队列的任务发出 review.overdue。"""
        project = await _create_project(client, seed)
        task = await _create_task(client, seed, project["id"])

        # P11-B72: promote to ready before assign
        task = await ready_task(client, task, seed.token)

        # Assign 并 submit 任务使其进入 IN_VERIFICATION
        resp = await client.post(
            f"/v1/tasks/{task['id']}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": task["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200
        assigned = resp.json()

        async with async_session_factory() as db:
            result = await db.execute(
                select(Verification).where(Verification.task_id == task["id"]),
            )
            vers = result.scalars().all()
            ver_id = vers[0].id

        resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Done",
                "evidence": {"output_access": {"type": "inline", "value": "task completed"}},
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed"},
                ],
                "expected_version": assigned["version_no"],
            },
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200

        # 手动回填 task.submitted 事件的时间戳以模拟过期审查
        async with async_session_factory() as db:
            stale_time = datetime.now(timezone.utc) - timedelta(days=2)
            stmt = (
                select(Event)
                .where(
                    Event.target_id == task["id"],
                    Event.event_type == "task.submitted",
                )
                .order_by(Event.created_at.desc())
                .limit(1)
            )
            event_result = await db.execute(stmt)
            submitted_ev = event_result.scalar_one_or_none()
            assert submitted_ev is not None, "task.submitted 事件必须存在"
            submitted_ev.created_at = stale_time.replace(tzinfo=None)
            await db.commit()

        # 触发失败检测 — 应检测到审查超时
        resp = await client.post(
            "/v1/admin/failure-detection/run",
            headers=auth_header(seed.token),
        )
        assert resp.status_code == 200, (
            f"失败检测端点返回 {resp.status_code}"
        )

        data = resp.json()
        assert data["lines"]["review"]["overdue_tasks"] >= 1, (
            f"期望 >=1 个逾期任务，实际 {data['lines']['review']['overdue_tasks']} 个"
        )
        assert task["id"] in data["lines"]["review"]["overdue_task_ids"]

        # 验证 review.overdue 事件已发射
        events = await _get_events(client, seed)
        overdue_events = [
            e for e in events
            if e["event_type"] == "review.overdue" and e["target_id"] == task["id"]
        ]
        assert len(overdue_events) >= 1, (
            f"期望 review.overdue 事件，实际 {len(overdue_events)} 个"
        )
        assert overdue_events[0]["payload"]["task_id"] == task["id"]
        assert "overdue_seconds" in overdue_events[0]["payload"]

        # 清理：取消任务以避免污染后续测试
        task_resp = await client.get(
            f"/v1/tasks/{task['id']}", headers=auth_header(seed.token),
        )
        if task_resp.status_code == 200:
            current = task_resp.json()
            await client.post(
                f"/v1/tasks/{task['id']}/cancel?expected_version={current['version_no']}",
                headers=auth_header(seed.token),
            )
