"""P100-B178 (PFL-273): ws_manager 多连接-per-actor 回归测试。

根因：``_connections`` 原为 ``dict[actor_id → WSClient]``（单连接 per actor），而前端
每页 Layout + 页面组件各开一条 WS（同 actor）。新连接踢旧连接 + ``disconnect`` 按
actor_id 误删新连接 → 同 actor 两条连接无限重连振荡，live-dot 永远到不了
``connected``。修复后支持同 actor 多连接，这里用最小 fake WebSocket 单元验证
ConnectionManager 语义（不碰 DB / HTTP）。
"""

import pytest
from starlette.websockets import WebSocketState

from src.constants import ActorType
from src.services.ws_manager import ConnectionManager, WSClient


class FakeWebSocket:
    """最小 WebSocket 替身 — 只实现 _safe_send/_safe_close 需要的接口。"""

    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.client_state = WebSocketState.DISCONNECTED


def make_client(actor_id: str = "act-1", team_id: str = "team-1") -> WSClient:
    return WSClient(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        team_id=team_id,
        name=None,
        ws=FakeWebSocket(),
    )


@pytest.fixture
def manager() -> ConnectionManager:
    """每个测试一个全新的 ConnectionManager，避免单例状态串扰。"""
    return ConnectionManager()


@pytest.mark.asyncio
async def test_two_connections_same_actor_coexist(manager: ConnectionManager) -> None:
    """第二条连接接入时不踢第一条（原缺陷：connect 关闭旧连接）。"""
    c1 = make_client()
    c2 = make_client()
    await manager.connect(c1)
    await manager.connect(c2)

    assert manager.connection_count == 2
    assert c1.ws.closed is False
    assert c2.ws.closed is False


@pytest.mark.asyncio
async def test_broadcast_to_actor_reaches_all_connections(manager: ConnectionManager) -> None:
    """broadcast_to_actor 应送达该 actor 的所有连接。"""
    c1 = make_client()
    c2 = make_client()
    await manager.connect(c1)
    await manager.connect(c2)

    await manager.broadcast_to_actor("act-1", {"type": "event", "data": {"x": 1}})

    assert len(c1.ws.sent) == 1
    assert len(c2.ws.sent) == 1
    assert c1.ws.sent[0]["type"] == "event"


@pytest.mark.asyncio
async def test_send_to_client_targets_only_that_connection(manager: ConnectionManager) -> None:
    """连接级响应（pong/error）只发给指定连接，不广播给同 actor 其它连接。"""
    c1 = make_client()
    c2 = make_client()
    await manager.connect(c1)
    await manager.connect(c2)

    await manager.send_to_client(c1, {"type": "pong"})

    assert len(c1.ws.sent) == 1
    assert len(c2.ws.sent) == 0


@pytest.mark.asyncio
async def test_disconnect_removes_only_specific_connection(manager: ConnectionManager) -> None:
    """断开一条连接不影响同 actor 的另一条（原缺陷：按 actor_id 误删新连接）。"""
    c1 = make_client()
    c2 = make_client()
    await manager.connect(c1)
    await manager.connect(c2)

    await manager.disconnect(c1)

    assert manager.connection_count == 1
    assert c1.ws.closed is True
    assert c2.ws.closed is False
    assert manager.team_connection_count("team-1") == 1


@pytest.mark.asyncio
async def test_disconnect_last_connection_cleans_team_index(manager: ConnectionManager) -> None:
    """最后一条连接断开后，team index 应清空。"""
    c1 = make_client()
    c2 = make_client()
    await manager.connect(c1)
    await manager.connect(c2)

    await manager.disconnect(c1)
    await manager.disconnect(c2)

    assert manager.connection_count == 0
    assert manager.team_connection_count("team-1") == 0


@pytest.mark.asyncio
async def test_subscribe_targets_specific_connection(manager: ConnectionManager) -> None:
    """订阅只作用于指定连接，不影响同 actor 的其它连接。"""
    c1 = make_client()
    c2 = make_client()
    await manager.connect(c1)
    await manager.connect(c2)

    await manager.subscribe(c1, ["task.created"])

    assert c1.subscribed_topics == {"task.created"}
    assert c2.subscribed_topics == set()


@pytest.mark.asyncio
async def test_broadcast_to_team_reaches_subscribed_connections(manager: ConnectionManager) -> None:
    """team 广播按连接级订阅过滤，命中订阅的连接（含同 actor 多条）。"""
    c1 = make_client()
    c2 = make_client()
    await manager.connect(c1)
    await manager.connect(c2)
    await manager.subscribe(c1, ["task.created"])  # 只 c1 订阅

    await manager.broadcast_to_team("team-1", {"event_type": "task.created", "id": "e1"})

    assert len(c1.ws.sent) == 1
    assert len(c2.ws.sent) == 0
