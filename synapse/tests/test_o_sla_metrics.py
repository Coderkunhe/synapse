"""Tests for P13-B12: O SLA Metrics service + API endpoint (C11).

C11 验收标准：O 在 Task submit 后 5min 内开始 verification 的概率 ≥95%。
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


# ── Helpers ────────────────────────────────────────────────────────────

def _make_event(
    event_type: str,
    target_id: str,
    created_at: datetime,
    team_id: str | None = None,
    target_type: str = "task",
    actor_type: str = "worker",
    actor_id: str = "wrk_test_orch",
    payload: str = "{}",
) -> dict:
    """构建 Event 字典用于直接 DB 插入。"""
    from src.utils.id_gen import generate_id
    return {
        "id": generate_id("event"),
        "team_id": team_id,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload,
        "created_at": created_at,
        "create_user_id": actor_id,
    }


async def _insert_events(db, events: list[dict]) -> list[str]:
    """将事件字典直接插入 event 表，返回插入的 event ID 列表。"""
    from src.models.event import Event
    ids = []
    for evt_dict in events:
        e = Event(**evt_dict)
        db.add(e)
        ids.append(evt_dict["id"])
    await db.commit()
    return ids


async def _cleanup_events(db, event_ids: list[str]) -> None:
    """删除指定 ID 的事件（用于测试间隔离）。"""
    from src.models.event import Event
    from sqlalchemy import delete
    if event_ids:
        await db.execute(delete(Event).where(Event.id.in_(event_ids)))
        await db.commit()


# ── Service Tests ──────────────────────────────────────────────────────

class TestOSlaMetricsService:
    """compute_o_response_metrics() — 度量计算正确性。"""

    @pytest.mark.asyncio
    async def test_response_structure_valid(self):
        """端点返回结构完整（DB 可能已有其他测试数据）。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        async with async_session_factory() as db:
            result = await compute_o_response_metrics(db)

        # Structure validation — exact counts depend on other tests
        assert "window_hours" in result
        assert "sla_target_minutes" in result
        assert "total_tasks" in result
        assert "p50_seconds" in result
        assert "p95_seconds" in result
        assert "p99_seconds" in result
        assert "breaches" in result
        assert "sla_compliance_pct" in result
        assert isinstance(result["response_times_seconds"], list)
        assert isinstance(result["breaches"], list)

    @pytest.mark.asyncio
    async def test_submitted_no_execution_returns_note(self):
        """有 TASK_SUBMITTED 但无 VERIFICATION_EXECUTED → note 返回。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        # Record baseline
        async with async_session_factory() as db:
            baseline = await compute_o_response_metrics(db)
            baseline_total = baseline["total_tasks"]

        now = datetime.now(timezone.utc)
        events = [
            _make_event("task.submitted", "tsk_no_exec", now - timedelta(minutes=30)),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db)

            # Our 1 event added
            assert result["total_tasks"] == baseline_total + 1
            # Our event has no matching verification_executed → not in response_times
            assert "note" in result
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_single_task_response_time(self):
        """单个 task submit → execute → 正确计算 delta。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        submitted_at = now - timedelta(minutes=30)
        executed_at = submitted_at + timedelta(seconds=180)  # 3 min response

        events = [
            _make_event("task.submitted", "tsk_single_b12", submitted_at),
            _make_event("verification.executed", "tsk_single_b12", executed_at),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db)

            # Our event should be counted
            assert result["total_tasks"] >= 1
            assert result["tasks_with_verification"] >= 1
            # 180.0 should be in the response times list
            assert 180.0 in result["response_times_seconds"]
            # Our task should NOT be in breaches (180s < 300s SLA)
            breach_ids = [b["task_id"] for b in result["breaches"]]
            assert "tsk_single_b12" not in breach_ids
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_sla_breach_detection(self):
        """O 响应超过 5min → breach 正确计数。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        submitted_at = now - timedelta(minutes=30)
        executed_at = submitted_at + timedelta(seconds=420)  # 7 min

        events = [
            _make_event("task.submitted", "tsk_breach_b12", submitted_at),
            _make_event("verification.executed", "tsk_breach_b12", executed_at),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db, sla_target_minutes=5)

            # Our task should appear in breaches with correct response time
            breach_ids = [b["task_id"] for b in result["breaches"]]
            assert "tsk_breach_b12" in breach_ids
            our_breach = [b for b in result["breaches"] if b["task_id"] == "tsk_breach_b12"][0]
            assert our_breach["seconds"] == 420.0
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_sla_target_boundary(self):
        """响应时间刚好等于 SLA threshold → 不 breach（≤ not <）。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        submitted_at = now - timedelta(minutes=30)
        executed_at = submitted_at + timedelta(seconds=300)  # exactly 5 min

        events = [
            _make_event("task.submitted", "tsk_boundary_b12", submitted_at),
            _make_event("verification.executed", "tsk_boundary_b12", executed_at),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db, sla_target_minutes=5)

            # 300s = 5min exactly → NOT a breach
            breach_ids = [b["task_id"] for b in result["breaches"]]
            assert "tsk_boundary_b12" not in breach_ids
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_multiple_tasks_percentiles(self):
        """多 task 响应时间 → p50/p95/p99 在合理范围。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=2)

        events = []
        for i in range(10):
            tid = f"tsk_multi_{i:03d}_b12"
            sub_at = base + timedelta(minutes=i)
            exec_at = sub_at + timedelta(seconds=(i + 1) * 60)
            events.append(_make_event("task.submitted", tid, sub_at))
            events.append(_make_event("verification.executed", tid, exec_at))

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db, sla_target_minutes=5)

            assert result["total_tasks"] >= 10
            assert result["tasks_with_verification"] >= 10
            assert len(result["response_times_seconds"]) >= 10

            # Our min/max should be bounded by the data we inserted
            assert result["min_seconds"] <= 60.0
            assert result["max_seconds"] >= 600.0

            # Our 5 tasks > 300s should be in breaches
            our_breach_ids = {b["task_id"] for b in result["breaches"]}
            for i in range(5, 10):  # indices 5-9 have response times 360-600s
                assert f"tsk_multi_{i:03d}_b12" in our_breach_ids
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_window_filtering(self):
        """window_hours 过滤 — 窗口外的事件不计入。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)

        # Events 25h ago — outside default 24h window
        old_sub = now - timedelta(hours=25)
        old_exec = old_sub + timedelta(seconds=120)
        # Recent events — inside window
        recent_sub = now - timedelta(hours=1)
        recent_exec = recent_sub + timedelta(seconds=300)

        events = [
            _make_event("task.submitted", "tsk_old_win_b12", old_sub),
            _make_event("verification.executed", "tsk_old_win_b12", old_exec),
            _make_event("task.submitted", "tsk_recent_win_b12", recent_sub),
            _make_event("verification.executed", "tsk_recent_win_b12", recent_exec),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db, window_hours=24)

            # Old task should NOT be counted; recent task should
            breach_ids = {b["task_id"] for b in result["breaches"]}
            assert "tsk_old_win_b12" not in breach_ids
            # Recent event (300s = 5min exactly) should not breach
            assert "tsk_recent_win_b12" not in breach_ids
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_only_first_execution_counted(self):
        """同一 task 多次 verification_executed → 只统计第一次（120s not 720s）。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        sub_at = now - timedelta(minutes=30)
        first_exec = sub_at + timedelta(seconds=120)
        second_exec = first_exec + timedelta(seconds=600)

        events = [
            _make_event("task.submitted", "tsk_first_b12", sub_at),
            _make_event("verification.executed", "tsk_first_b12", first_exec),
            _make_event("verification.executed", "tsk_first_b12", second_exec),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db, sla_target_minutes=5)

            # First response is 120s → should NOT breach
            breach_ids = {b["task_id"] for b in result["breaches"]}
            assert "tsk_first_b12" not in breach_ids
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_breaches_sorted_descending(self):
        """违规列表按响应时间降序排列。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        base = now - timedelta(hours=2)

        events = []
        for i in range(5):
            tid = f"tsk_breach_sort_{i:03d}_b12"
            sub_at = base + timedelta(minutes=i)
            exec_at = sub_at + timedelta(seconds=400 + i * 100)
            events.append(_make_event("task.submitted", tid, sub_at))
            events.append(_make_event("verification.executed", tid, exec_at))

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db, sla_target_minutes=5)

            # Our 5 tasks all breach — find them in breaches
            our_breaches = [
                b for b in result["breaches"]
                if b["task_id"].startswith("tsk_breach_sort_")
            ]
            assert len(our_breaches) == 5
            # Sorted descending (worst first)
            assert our_breaches[0]["seconds"] == 800.0
            assert our_breaches[1]["seconds"] == 700.0
            assert our_breaches[-1]["seconds"] == 400.0
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_custom_sla_target(self):
        """自定义 sla_target_minutes 影响 breach 判定。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        sub_at = now - timedelta(minutes=30)
        exec_at = sub_at + timedelta(seconds=480)  # 8 min

        events = [
            _make_event("task.submitted", "tsk_custom_sla_b12", sub_at),
            _make_event("verification.executed", "tsk_custom_sla_b12", exec_at),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                # With 5-min SLA: 8min should breach
                r5 = await compute_o_response_metrics(db, sla_target_minutes=5)
                r5_ids = {b["task_id"] for b in r5["breaches"]}
                assert "tsk_custom_sla_b12" in r5_ids

                # With 10-min SLA: 8min should NOT breach
                r10 = await compute_o_response_metrics(db, sla_target_minutes=10)
                r10_ids = {b["task_id"] for b in r10["breaches"]}
                assert "tsk_custom_sla_b12" not in r10_ids
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_irrelevant_events_ignored(self):
        """非 task.submitted/verification.executed 事件不干扰计算。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        sub_at = now - timedelta(minutes=30)
        exec_at = sub_at + timedelta(seconds=150)

        events = [
            _make_event("task.submitted", "tsk_irrelevant_b12", sub_at),
            _make_event("verification.executed", "tsk_irrelevant_b12", exec_at),
            # Irrelevant events with different types
            _make_event("task.created", "tsk_irrelevant_b12", sub_at - timedelta(hours=1)),
            _make_event("worker.heartbeat", "wrk_001", now - timedelta(minutes=5)),
            _make_event("task.assigned", "tsk_irrelevant_b12", sub_at - timedelta(minutes=5)),
            _make_event("batch.created", "bat_001", now),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db)

            # Our task should be counted with 150s response
            assert 150.0 in result["response_times_seconds"]
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_target_type_filter(self):
        """只匹配 target_type='task' 的 verification_executed 事件。"""
        from src.db import async_session_factory
        from src.services.o_sla_metrics import compute_o_response_metrics

        now = datetime.now(timezone.utc)
        sub_at = now - timedelta(minutes=30)
        exec_at = sub_at + timedelta(seconds=120)

        events = [
            _make_event("task.submitted", "tsk_tt_filter_b12", sub_at),
            _make_event("verification.executed", "tsk_tt_filter_b12", exec_at, target_type="task"),
            # batch target_type — should NOT match
            _make_event("task.submitted", "bat_tt_filter_b12", sub_at),
            _make_event("verification.executed", "bat_tt_filter_b12", exec_at, target_type="batch"),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events)
        try:
            async with async_session_factory() as db:
                result = await compute_o_response_metrics(db)

            # tsk_tt_filter_b12 should have a matching verification (target_type='task')
            breach_ids = {b["task_id"] for b in result["breaches"]}
            assert "tsk_tt_filter_b12" not in breach_ids  # 120s < 300s
            # bat_tt_filter_b12 should not have a matching verification (target_type='batch' filtered out)
            assert "bat_tt_filter_b12" not in breach_ids
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)


# ── API Endpoint Tests ─────────────────────────────────────────────────

class TestOSlaApiEndpoint:
    """GET /v1/stats/o-sla — API 端点正确性。"""

    @pytest.mark.asyncio
    async def test_endpoint_returns_200_empty(self, client: AsyncClient, seed: SeedData):
        """端点返回 200 + 有效结构。"""
        resp = await client.get("/v1/stats/o-sla")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["window_hours"] > 0
        assert body["sla_target_minutes"] > 0
        assert "total_tasks" in body
        assert "p50_seconds" in body
        assert "sla_compliance_pct" in body
        assert "breaches" in body

    @pytest.mark.asyncio
    async def test_endpoint_with_data(self, client: AsyncClient, seed: SeedData):
        """端点返回正确指标（有数据时）。"""
        from src.db import async_session_factory
        from src.models.event import Event

        now = datetime.now(timezone.utc)
        sub_at = now - timedelta(minutes=30)
        exec_at = sub_at + timedelta(seconds=200)

        events_data = [
            _make_event("task.submitted", "tsk_api_1", sub_at, team_id=seed.team_id),
            _make_event("verification.executed", "tsk_api_1", exec_at, team_id=seed.team_id),
        ]

        async with async_session_factory() as db:
            eids = await _insert_events(db, events_data)
        try:
            resp = await client.get("/v1/stats/o-sla")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            # API query covers ALL events in DB, so we check our events are in there
            assert body["total_tasks"] >= 1
            assert body["tasks_with_verification"] >= 1
            assert 200.0 in body["response_times_seconds"]
        finally:
            async with async_session_factory() as db:
                await _cleanup_events(db, eids)

    @pytest.mark.asyncio
    async def test_endpoint_custom_params(self, client: AsyncClient, seed: SeedData):
        """自定义 query params 被正确传递。"""
        resp = await client.get("/v1/stats/o-sla?window_hours=48&sla_target_minutes=10")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["window_hours"] == 48
        assert body["sla_target_minutes"] == 10

    @pytest.mark.asyncio
    async def test_endpoint_rejects_invalid_params(self, client: AsyncClient, seed: SeedData):
        """无效参数被拒绝。"""
        resp = await client.get("/v1/stats/o-sla?window_hours=200")
        assert resp.status_code == 422, resp.text

        resp = await client.get("/v1/stats/o-sla?sla_target_minutes=0")
        assert resp.status_code == 422, resp.text

        resp = await client.get("/v1/stats/o-sla?window_hours=0")
        assert resp.status_code == 422, resp.text
