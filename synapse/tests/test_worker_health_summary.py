"""P16-B6 任务 B：GET /v1/workers/{worker_id}/health-summary。

``last_heartbeat_at`` 只能回答「最后一跳是什么时候」。本端点消费任务 A 落库的
``worker.heartbeat`` 事件，回答「窗口内跳了多少次、平均多久一跳、现在还在不在线」。

覆盖：
- 响应契约：六个字段名精确匹配（O 定义，不得擅改）
- heartbeat_count：只数窗口内的事件，窗口外的不算
- avg_interval_seconds：窗口内 < 2 跳为 null；≥ 2 跳为 (末-首)/(跳数-1)
- is_online：复用 provider 心跳阈值（claude 300s / codex 1800s），不新造常量
- 从未心跳的 Worker → last_heartbeat_at=null · count=0 · avg=null · is_online=false
- 错误路径：worker 不存在 404 · 跨 team 404 · 未认证 401
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from src.constants import ActorType, EventType
from tests.conftest import SeedData, auth_header


# ═══════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════


async def _register_worker(
    client: AsyncClient,
    seed: SeedData,
    name: str,
    *,
    provider: str = "claude",
    handshake: bool = True,
) -> dict:
    """注册 Worker（可选握手），**不发心跳** — 保证心跳事件由测试自己控制。

    握手会写 ``last_heartbeat_at``（PFL-065）但不写 ``worker.heartbeat`` 事件，
    因此握手后的 Worker 是「在线但零心跳事件」的干净起点。
    """
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/agents",
        json={"name": name, "provider": provider, "provider_model": "default"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, f"Worker register failed: {resp.text}"
    data = resp.json()
    worker_id = data["worker"]["id"]
    api_key = data["api_key"]

    if handshake:
        hs = await client.post(
            f"/v1/agents/{worker_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [],
                "supported_events": ["task.assigned"],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )
        assert hs.status_code == 200, f"Handshake failed: {hs.text}"

    return {"worker_id": worker_id, "api_key": api_key}


async def _seed_heartbeat_events(
    team_id: str, worker_id: str, ages_seconds: list[int]
) -> None:
    """按「距今多少秒」直接写入 worker.heartbeat 事件。

    ``Event.created_at`` 是 naive UTC 列，测试写入时同样去掉 tzinfo，
    与生产写入路径（``_utcnow``）保持一致。
    """
    from src.db import async_session_factory
    from src.models.event import Event
    from src.utils.id_gen import generate_id

    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        for age in ages_seconds:
            db.add(
                Event(
                    id=generate_id("event"),
                    team_id=team_id,
                    event_type=EventType.WORKER_HEARTBEAT,
                    actor_type=ActorType.WORKER,
                    actor_id=worker_id,
                    target_type="worker",
                    target_id=worker_id,
                    payload=json.dumps({"current_load": 0, "active_task_id": None}),
                    created_at=(now - timedelta(seconds=age)).replace(tzinfo=None),
                )
            )
        await db.commit()


async def _age_heartbeat(worker_id: str, seconds: int) -> None:
    """把 Worker.last_heartbeat_at 拨回过去 N 秒。"""
    from src.db import async_session_factory
    from tests.harness.time_travel import TimeTravel

    async with async_session_factory() as db:
        await TimeTravel(db).age_heartbeat(worker_id, seconds=seconds)
        await db.commit()


async def _get_summary(
    client: AsyncClient, worker_id: str, token: str, **params
) -> tuple[int, dict]:
    resp = await client.get(
        f"/v1/workers/{worker_id}/health-summary",
        params=params or None,
        headers=auth_header(token),
    )
    return resp.status_code, (resp.json() if resp.content else {})


CONTRACT_FIELDS = {
    "worker_id",
    "last_heartbeat_at",
    "heartbeat_count",
    "avg_interval_seconds",
    "is_online",
    "window_hours",
}


# ═══════════════════════════════════════════════════════════════════
# 响应契约
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestHealthSummaryContract:
    """O 定义的响应契约 — 字段名和默认窗口不得漂移。"""

    async def test_response_has_exactly_the_contract_fields(
        self, client: AsyncClient, seed: SeedData
    ):
        w = await _register_worker(client, seed, "HS-Contract")

        status, body = await _get_summary(client, w["worker_id"], seed.token)

        assert status == 200, body
        assert set(body.keys()) == CONTRACT_FIELDS, (
            f"响应字段与契约不一致：多出 {set(body) - CONTRACT_FIELDS}，"
            f"缺失 {CONTRACT_FIELDS - set(body)}"
        )
        assert body["worker_id"] == w["worker_id"]

    async def test_window_hours_defaults_to_24_and_echoes_override(
        self, client: AsyncClient, seed: SeedData
    ):
        w = await _register_worker(client, seed, "HS-Window")

        _, default_body = await _get_summary(client, w["worker_id"], seed.token)
        assert default_body["window_hours"] == 24

        _, custom_body = await _get_summary(
            client, w["worker_id"], seed.token, window_hours=6
        )
        assert custom_body["window_hours"] == 6


# ═══════════════════════════════════════════════════════════════════
# 计数与平均间隔
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestHeartbeatAggregation:
    """count / avg 来自窗口内的 worker.heartbeat 事件。"""

    async def test_never_heartbeat_worker_reports_zero(
        self, client: AsyncClient, seed: SeedData
    ):
        """从未心跳（未握手）→ 三个字段全部走空值分支，且不是 500。"""
        w = await _register_worker(client, seed, "HS-Never", handshake=False)

        status, body = await _get_summary(client, w["worker_id"], seed.token)

        assert status == 200, body
        assert body["last_heartbeat_at"] is None
        assert body["heartbeat_count"] == 0
        assert body["avg_interval_seconds"] is None
        assert body["is_online"] is False

    async def test_single_heartbeat_has_no_interval(
        self, client: AsyncClient, seed: SeedData
    ):
        """1 跳没有「间隔」可言 → avg 为 null，不拿 0 冒充。"""
        w = await _register_worker(client, seed, "HS-Single")
        await _seed_heartbeat_events(seed.team_id, w["worker_id"], [60])

        _, body = await _get_summary(client, w["worker_id"], seed.token)

        assert body["heartbeat_count"] == 1
        assert body["avg_interval_seconds"] is None

    async def test_evenly_spaced_heartbeats_average_to_the_gap(
        self, client: AsyncClient, seed: SeedData
    ):
        """4 跳、每 60s 一次 → count=4, avg=60.0。"""
        w = await _register_worker(client, seed, "HS-Even")
        await _seed_heartbeat_events(
            seed.team_id, w["worker_id"], [240, 180, 120, 60]
        )

        _, body = await _get_summary(client, w["worker_id"], seed.token)

        assert body["heartbeat_count"] == 4
        assert body["avg_interval_seconds"] == pytest.approx(60.0, abs=0.01)

    async def test_uneven_heartbeats_average_over_gap_count(
        self, client: AsyncClient, seed: SeedData
    ):
        """跨度 300s / 3 个间隔 → avg=100.0（除以间隔数，不是跳数）。"""
        w = await _register_worker(client, seed, "HS-Uneven")
        await _seed_heartbeat_events(
            seed.team_id, w["worker_id"], [330, 300, 90, 30]
        )

        _, body = await _get_summary(client, w["worker_id"], seed.token)

        assert body["heartbeat_count"] == 4
        assert body["avg_interval_seconds"] == pytest.approx(100.0, abs=0.01)

    async def test_events_outside_window_are_excluded(
        self, client: AsyncClient, seed: SeedData
    ):
        """窗口是过滤器：2 跳在窗口内，2 跳在窗口外。"""
        w = await _register_worker(client, seed, "HS-Outside")
        two_days = 2 * 24 * 3600
        await _seed_heartbeat_events(
            seed.team_id,
            w["worker_id"],
            [two_days + 120, two_days + 60, 120, 60],
        )

        _, default_body = await _get_summary(client, w["worker_id"], seed.token)
        assert default_body["heartbeat_count"] == 2, "24h 窗口应只数近 2 跳"
        assert default_body["avg_interval_seconds"] == pytest.approx(60.0, abs=0.01)

        _, wide_body = await _get_summary(
            client, w["worker_id"], seed.token, window_hours=72
        )
        assert wide_body["heartbeat_count"] == 4, "72h 窗口应把 2 天前的 2 跳也数上"

    async def test_other_workers_heartbeats_are_not_counted(
        self, client: AsyncClient, seed: SeedData
    ):
        """同 team 另一个 Worker 的心跳不得串台。"""
        mine = await _register_worker(client, seed, "HS-Mine")
        other = await _register_worker(client, seed, "HS-Other")
        await _seed_heartbeat_events(seed.team_id, mine["worker_id"], [120, 60])
        await _seed_heartbeat_events(
            seed.team_id, other["worker_id"], [300, 240, 180]
        )

        _, body = await _get_summary(client, mine["worker_id"], seed.token)

        assert body["heartbeat_count"] == 2

    async def test_real_heartbeat_endpoint_feeds_the_summary(
        self, client: AsyncClient, seed: SeedData
    ):
        """端到端：真心跳 API 打 3 次 → 摘要读到 3 跳（不依赖测试直插事件）。"""
        w = await _register_worker(client, seed, "HS-E2E")

        for _ in range(3):
            hb = await client.post(
                f"/v1/agents/{w['worker_id']}/heartbeat",
                json={"current_load": 0},
                headers=auth_header(w["api_key"]),
            )
            assert hb.status_code == 200, hb.text

        _, body = await _get_summary(client, w["worker_id"], seed.token)

        assert body["heartbeat_count"] == 3
        assert body["avg_interval_seconds"] is not None
        assert body["is_online"] is True


# ═══════════════════════════════════════════════════════════════════
# 在线判定
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestOnlineDecision:
    """阈值复用 provider 配置注册中心（failure_detector 的同一 helper）。"""

    async def test_recent_heartbeat_is_online(
        self, client: AsyncClient, seed: SeedData
    ):
        w = await _register_worker(client, seed, "HS-Fresh")

        _, body = await _get_summary(client, w["worker_id"], seed.token)

        assert body["is_online"] is True
        assert body["last_heartbeat_at"] is not None

    async def test_claude_worker_offline_past_300s(
        self, client: AsyncClient, seed: SeedData
    ):
        """claude 阈值 300s：299s 前仍在线，301s 前已离线。"""
        near = await _register_worker(client, seed, "HS-Near", provider="claude")
        past = await _register_worker(client, seed, "HS-Past", provider="claude")

        await _age_heartbeat(near["worker_id"], 299)
        await _age_heartbeat(past["worker_id"], 301)

        _, near_body = await _get_summary(client, near["worker_id"], seed.token)
        _, past_body = await _get_summary(client, past["worker_id"], seed.token)

        assert near_body["is_online"] is True
        assert past_body["is_online"] is False

    async def test_codex_worker_uses_1800s_threshold(
        self, client: AsyncClient, seed: SeedData
    ):
        """同样 600s 无心跳：claude 判离线，codex 仍在线 —— 阈值随 provider 走。"""
        claude = await _register_worker(client, seed, "HS-C", provider="claude")
        codex = await _register_worker(client, seed, "HS-X", provider="codex")

        await _age_heartbeat(claude["worker_id"], 600)
        await _age_heartbeat(codex["worker_id"], 600)

        _, claude_body = await _get_summary(client, claude["worker_id"], seed.token)
        _, codex_body = await _get_summary(client, codex["worker_id"], seed.token)

        assert claude_body["is_online"] is False
        assert codex_body["is_online"] is True

    async def test_offline_worker_still_reports_its_heartbeat_history(
        self, client: AsyncClient, seed: SeedData
    ):
        """离线不清零历史 —— 排障恰恰要看「掉线前跳得稳不稳」。"""
        w = await _register_worker(client, seed, "HS-OfflineHist")
        await _seed_heartbeat_events(seed.team_id, w["worker_id"], [900, 840, 780])
        await _age_heartbeat(w["worker_id"], 780)

        _, body = await _get_summary(client, w["worker_id"], seed.token)

        assert body["is_online"] is False
        assert body["heartbeat_count"] == 3
        assert body["avg_interval_seconds"] == pytest.approx(60.0, abs=0.01)


# ═══════════════════════════════════════════════════════════════════
# 错误路径
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestHealthSummaryErrors:
    async def test_unknown_worker_returns_404(
        self, client: AsyncClient, seed: SeedData
    ):
        status, _ = await _get_summary(client, "ag_does_not_exist", seed.token)
        assert status == 404

    async def test_cross_team_worker_returns_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """跨 team 查询与「不存在」同构 —— 不泄漏他 team 的 Worker 是否存在。"""
        from src.auth import create_access_token
        from src.models.member import Member
        from src.models.team import Team
        from src.db import async_session_factory
        from src.utils.id_gen import derive_id, generate_id

        w = await _register_worker(client, seed, "HS-CrossTeam")

        other_team_id = generate_id("team")
        other_member_id = generate_id("member")
        short = uuid.uuid4().hex[:12]
        async with async_session_factory() as db:
            db.add_all(
                [
                    Team(id=other_team_id, name=f"Other {short}", slug=f"other-{short}"),
                    Member(
                        id=other_member_id,
                        team_id=other_team_id,
                        user_id=f"user-{short}",
                        display_name="Other Admin",
                        role="admin",
                    ),
                ]
            )
            await db.commit()

        other_token = create_access_token(
            user_id=f"user-{short}",
            actor_id=derive_id(other_member_id, "worker"),
            team_id=other_team_id,
            role="admin",
        )

        status, _ = await _get_summary(client, w["worker_id"], other_token)
        assert status == 404

    async def test_missing_token_returns_401(
        self, client: AsyncClient, seed: SeedData
    ):
        w = await _register_worker(client, seed, "HS-NoAuth")

        resp = await client.get(f"/v1/workers/{w['worker_id']}/health-summary")

        assert resp.status_code == 401

    async def test_invalid_window_hours_rejected(
        self, client: AsyncClient, seed: SeedData
    ):
        """window_hours 有边界 —— 0 或负数不是合法统计窗口。"""
        w = await _register_worker(client, seed, "HS-BadWindow")

        status, _ = await _get_summary(
            client, w["worker_id"], seed.token, window_hours=0
        )
        assert status == 422
