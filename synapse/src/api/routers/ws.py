"""WebSocket endpoint — real-time event channel.

Endpoint:  /v1/ws (auth: ?token=<jwt_or_apikey> query param, or access_token httpOnly cookie)
Protocol:  JSON messages over WebSocket (see protocol.md §2.2 and §10)

Client → Server messages:
    {"type": "subscribe", "topics": ["task.assigned", "task.completed"]}
    {"type": "unsubscribe", "topics": ["task.assigned"]}
    {"type": "ping"}

Server → Client messages:
    {"type": "pong"}
    {"type": "event", "data": {...}}
    {"type": "error", "detail": "..."}
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import decode_access_token, verify_api_key
from src.config import settings
from src.constants import ActorType, EventType
from src.db import async_session_factory
from src.services.ws_manager import HEARTBEAT_INTERVAL, ws_manager, WSClient

router = APIRouter()


# ── Token verification for WebSocket ───────────────────────────────────────────


async def _verify_ws_token(token: str) -> dict[str, Any] | None:
    """Verify a token from WebSocket query param.

    Returns actor info dict on success, None on failure.
    """
    # Try API Key first (worker auth)
    if token.startswith("sk-syn-"):
        async with async_session_factory() as db:
            try:
                agent_info = await verify_api_key(token, db)
                if agent_info:
                    return agent_info
            finally:
                await db.close()
        return None

    # Otherwise treat as JWT (actor auth — human via OAuth)
    try:
        payload = decode_access_token(token)
        return {
            "actor_type": payload.get("actor_type", ActorType.HUMAN),
            "actor_id": payload.get("actorId", payload.get("memberId", payload["sub"])),
            "team_id": payload.get("teamId", payload.get("team_id", "")),
            "name": None,
        }
    except Exception:
        return None


# ── Message handlers ───────────────────────────────────────────────────────────


async def _handle_message(client: WSClient, raw: str) -> None:
    """Parse and dispatch a single client message."""
    try:
        msg: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        await ws_manager.send_to_client(
            client,
            {"type": "error", "detail": "Invalid JSON"},
        )
        return

    # Rate limit check
    if not ws_manager.check_rate_limit(client):
        await ws_manager.send_to_client(
            client,
            {"type": "error", "detail": "Rate limit exceeded"},
        )
        return

    msg_type = msg.get("type", "")

    if msg_type == "subscribe":
        topics: list[str] = msg.get("topics", [])
        await ws_manager.subscribe(client, topics)

    elif msg_type == "unsubscribe":
        topics = msg.get("topics", [])
        await ws_manager.unsubscribe(client, topics)

    elif msg_type == "ping":
        await ws_manager.update_pong(client)
        await ws_manager.send_to_client(client, {"type": "pong"})

    else:
        await ws_manager.send_to_client(
            client,
            {"type": "error", "detail": f"Unknown message type: {msg_type}"},
        )


# ── Heartbeat sender ───────────────────────────────────────────────────────────


async def _heartbeat_sender(client: WSClient, stop_event: asyncio.Event) -> None:
    """Periodically send ping frames and check for timeout.

    Runs as a background task alongside the message reader. Sends a JSON
    ping every HEARTBEAT_INTERVAL seconds. If the client's last_pong
    exceeds the timeout, this task closes the WebSocket to trigger
    cleanup in the main loop.
    """
    try:
        while not stop_event.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if stop_event.is_set():
                break

            elapsed = time.monotonic() - client.last_pong
            if elapsed > HEARTBEAT_INTERVAL * 2:
                # Client hasn't ponged for two intervals — disconnect
                stop_event.set()
                break

            # Send ping
            try:
                await client.ws.send_json({"type": "ping"})
            except Exception:
                stop_event.set()
                break
    except asyncio.CancelledError:
        pass


# ── WebSocket endpoint ─────────────────────────────────────────────────────────


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str | None = Query(None),
) -> None:
    """Upgrade to WebSocket and handle the event stream.

    Authentication:
        token (query, optional): JWT (member) or API Key (worker).
        access_token (cookie): browser clients authenticate via the httpOnly
        ``access_token`` cookie (P100-B58), sent automatically on the WS
        handshake when same-site — no ``?token=`` query param.

    P100-B171: browser clients no longer pass ``?token=``; the cookie is the
    primary auth channel (symmetric with ``dependencies.get_current_actor``).
    The query param is retained for Workers using ``?token=sk-syn-…`` API keys.
    """
    # P100-B171: cookie fallback — browser clients authenticate via the httpOnly
    # access_token cookie. Query param still honored first (Worker API keys).
    if not token:
        token = ws.cookies.get(settings.access_token_cookie_name)

    # Verify token BEFORE accepting the connection.
    # We validate first, then accept/close — this avoids Starlette
    # returning an opaque HTTP 403 on failed auth.
    if not token:
        await ws.accept()
        await ws.close(code=4001, reason="Missing token")
        return

    actor = await _verify_ws_token(token)
    if actor is None:
        await ws.accept()
        await ws.close(code=4001, reason="Invalid or expired token")
        return

    await ws.accept()

    client = WSClient(
        actor_id=actor["actor_id"],
        actor_type=actor["actor_type"],
        team_id=actor["team_id"],
        name=actor.get("name"),
        ws=ws,
        # Auto-subscribe all topics for the actor's team
        subscribed_topics=set(),
    )

    # P11-B23: 连接数上限 — 超过限制则拒绝新连接
    if ws_manager.connection_count >= settings.ws_max_connections:
        await ws.send_json({
            "type": "error",
            "detail": f"Too many connections (max {settings.ws_max_connections})",
        })
        await ws.close(code=4013, reason="Too many connections")
        return

    await ws_manager.connect(client)

    # P10-B32: Auto-subscribe Workers to authorization request topics
    # P11-B21 PFL-041: Auto-subscribe ALL actors to task lifecycle topics
    task_topics = [
        EventType.TASK_CREATED,
        EventType.TASK_READIED,
        EventType.TASK_ASSIGNED,
        EventType.TASK_CLAIMED,
        EventType.TASK_SUBMITTED,
        EventType.TASK_COMPLETED,
        EventType.TASK_REJECTED,
        EventType.TASK_CANCELLED,
        EventType.TASK_PAUSED,
        EventType.TASK_RESUMED,
    ]
    if actor["actor_type"] == ActorType.WORKER:
        await ws_manager.subscribe(
            client,
            [
                EventType.AUTHORIZATION_REQUEST_CREATED,
                EventType.AUTHORIZATION_REQUEST_RESPONDED,
                EventType.AUTHORIZATION_REQUEST_EXPIRED,
                EventType.AUTHORIZATION_REQUEST_CANCELLED,
                *task_topics,
            ],
        )
    else:
        # P11-B21: Humans auto-subscribe to task topics for real-time VDD loop
        # P11-B22: + authorization_request.* for real-time Approvals page updates
        await ws_manager.subscribe(
            client,
            [
                *task_topics,
                EventType.AUTHORIZATION_REQUEST_CREATED,
                EventType.AUTHORIZATION_REQUEST_RESPONDED,
                EventType.AUTHORIZATION_REQUEST_EXPIRED,
                EventType.AUTHORIZATION_REQUEST_CANCELLED,
            ],
        )

    # Send welcome message
    await ws_manager.send_to_client(
        client,
        {
            "type": "connected",
            "actor_id": client.actor_id,
            "actor_type": client.actor_type,
            "team_id": client.team_id,
        },
    )

    stop_event = asyncio.Event()

    try:
        # Start heartbeat sender in background
        heartbeat_task = asyncio.create_task(_heartbeat_sender(client, stop_event))

        # Message reader loop
        while not stop_event.is_set():
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=HEARTBEAT_INTERVAL + 5)
                # P11-B23: 消息大小限制 — 拒绝超大消息
                if len(raw) > settings.ws_max_message_size:
                    await ws_manager.send_to_client(
                        client,
                        {
                            "type": "error",
                            "detail": f"Message too large: {len(raw)} bytes "
                            f"(max {settings.ws_max_message_size})",
                        },
                    )
                    continue
                await _handle_message(client, raw)
            except asyncio.TimeoutError:
                # No message received within timeout — check if client is still alive
                if time.monotonic() - client.last_pong > HEARTBEAT_INTERVAL * 2:
                    stop_event.set()
                continue

    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        await ws_manager.disconnect(client)
