"""P100-B171: WebSocket auth via httpOnly cookie fallback.

B171 root fix — browser clients authenticate the WS handshake via the
httpOnly ``access_token`` cookie (auto-sent, no ``?token=`` query param),
mirroring HTTP auth in ``dependencies.get_current_actor``.

Uses a synchronous ``starlette.testclient.TestClient`` because the async
``client`` fixture (httpx ASGITransport) does not support WebSocket transport.
The JWT path under test never touches the DB, so no DB setup is required.
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.auth import create_access_token
from src.main import create_app

COOKIE_NAME = "access_token"


def _make_token() -> str:
    """A valid human JWT for a fresh actor (no DB round-trip on the JWT path)."""
    return create_access_token(
        user_id="usr_test_ws",
        actor_id="act_test_ws",
        team_id="tea_test_ws",
        role="admin",
    )


def test_ws_cookie_auth_without_query_token() -> None:
    """Browser client connects with the cookie only (no ?token=) → connected."""
    app = create_app()
    token = _make_token()

    client = TestClient(app)
    try:
        client.cookies.set(COOKIE_NAME, token, path="/v1")
        with client.websocket_connect("/v1/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["actor_id"] == "act_test_ws"
            assert msg["team_id"] == "tea_test_ws"
    finally:
        client.close()


def test_ws_query_token_still_supported() -> None:
    """Regression guard — the ?token= query param path is preserved."""
    app = create_app()
    token = _make_token()

    client = TestClient(app)
    try:
        with client.websocket_connect(f"/v1/ws?token={token}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["actor_id"] == "act_test_ws"
    finally:
        client.close()


def test_ws_missing_token_closes_4001() -> None:
    """Neither cookie nor query token → server closes with 4001."""
    app = create_app()

    client = TestClient(app)
    try:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/v1/ws") as ws:
                ws.receive_json()
        assert exc_info.value.code == 4001
    finally:
        client.close()
