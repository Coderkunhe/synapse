"""WebSocket 连接管理器 — 发布/订阅 + 心跳。

管理活跃 WebSocket 连接、基于主题的订阅，
并向已连接客户端实时广播事件。

架构：
    ws_manager（单例）──► ConnectionManager
        ├── _connections: {actor_id → WebSocket}
        ├── _subscriptions: {actor_id → set[topic]}
        └── _team_index: {team_id → set[actor_id]}
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from src.constants import ActorType, EventType

# ── 常量 ──────────────────────────────────────────────────────────────────

HEARTBEAT_INTERVAL = 30  # ping/pong 间隔秒数
HEARTBEAT_TIMEOUT = 60   # 连接被视为断开的超时秒数
RATE_LIMIT_WORKER = 10    # Worker 每秒最大消息数
RATE_LIMIT_MEMBER = 50   # 成员每秒最大消息数

# 所有可订阅的事件主题（镜像 EventType 枚举）
TOPICS: set[str] = {e.value for e in EventType}


# ── 数据类型 ─────────────────────────────────────────────────────────────────


@dataclass
class WSClient:
    """单条 WebSocket 连接的元数据。"""

    actor_id: str
    actor_type: str  # ActorType.WORKER | ActorType.HUMAN
    team_id: str
    name: str | None
    ws: WebSocket
    subscribed_topics: set[str] = field(default_factory=set)
    last_pong: float = field(default_factory=time.monotonic)
    message_timestamps: list[float] = field(default_factory=list)


# ── 连接管理器 ─────────────────────────────────────────────────────────


class ConnectionManager:
    """线程安全的 WebSocket 连接管理器，支持发布/订阅。"""

    def __init__(self) -> None:
        self._connections: dict[str, WSClient] = {}          # actor_id → WSClient
        self._team_index: dict[str, set[str]] = {}            # team_id → {actor_id}
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── 连接生命周期 ───────────────────────────────────────────────

    async def connect(self, client: WSClient) -> None:
        """注册新的 WebSocket 连接。"""
        async with self._lock:
            # 若同一 actor 已有连接则关闭旧连接
            if client.actor_id in self._connections:
                existing = self._connections[client.actor_id]
                await self._safe_close(existing.ws)

            self._connections[client.actor_id] = client
            self._team_index.setdefault(client.team_id, set()).add(client.actor_id)

    async def disconnect(self, actor_id: str) -> None:
        """移除 WebSocket 连接。"""
        async with self._lock:
            client = self._connections.pop(actor_id, None)
            if client is None:
                return
            team_members = self._team_index.get(client.team_id)
            if team_members:
                team_members.discard(actor_id)
                if not team_members:
                    del self._team_index[client.team_id]
            await self._safe_close(client.ws)

    # ── 订阅管理 ────────────────────────────────────────────

    async def subscribe(self, actor_id: str, topics: list[str]) -> None:
        """订阅一个或多个事件主题。"""
        client = self._connections.get(actor_id)
        if client is None:
            return
        valid_topics = [t for t in topics if t in TOPICS]
        client.subscribed_topics.update(valid_topics)

    async def unsubscribe(self, actor_id: str, topics: list[str]) -> None:
        """取消订阅一个或多个事件主题。"""
        client = self._connections.get(actor_id)
        if client is None:
            return
        client.subscribed_topics.difference_update(topics)

    # ── 广播 ──────────────────────────────────────────────────────────

    async def broadcast_to_team(self, team_id: str, event: dict[str, Any]) -> None:
        """将事件推送给团队中所有匹配主题的订阅者。

        由 event_store.record() 在写入事件到数据库后调用。
        event 字典必须至少包含 ``event_type``。
        """
        topic = event.get("event_type", "")
        async with self._lock:
            actor_ids = list(self._team_index.get(team_id, set()))

        for actor_id in actor_ids:
            client = self._connections.get(actor_id)
            if client is None:
                continue
            if topic not in client.subscribed_topics:
                continue
            await self._safe_send(client, {"type": "event", "data": event})

    async def broadcast_to_actor(self, actor_id: str, message: dict[str, Any]) -> None:
        """直接向特定 actor 发送消息。"""
        client = self._connections.get(actor_id)
        if client is None:
            return
        await self._safe_send(client, message)

    # ── 心跳 ──────────────────────────────────────────────────────────

    async def update_pong(self, actor_id: str) -> None:
        """记录客户端的 pong 响应。"""
        client = self._connections.get(actor_id)
        if client:
            client.last_pong = time.monotonic()

    async def check_heartbeats(self) -> list[str]:
        """检查所有连接的心跳超时。

        返回已超时应断开连接的 actor_id 列表。
        """
        now = time.monotonic()
        timed_out: list[str] = []
        async with self._lock:
            for actor_id, client in list(self._connections.items()):
                if now - client.last_pong > HEARTBEAT_TIMEOUT:
                    timed_out.append(actor_id)
        return timed_out

    async def reap_dead_connections(self) -> int:
        """断开所有已超时的客户端。返回断开数量。"""
        dead = await self.check_heartbeats()
        for actor_id in dead:
            await self.disconnect(actor_id)
        return len(dead)

    # ── 速率限制 ──────────────────────────────────────────────────────

    def check_rate_limit(self, actor_id: str) -> bool:
        """若 actor 在速率限制内则返回 True。"""
        client = self._connections.get(actor_id)
        if client is None:
            return True
        now = time.monotonic()
        limit = RATE_LIMIT_WORKER if client.actor_type == ActorType.WORKER else RATE_LIMIT_MEMBER
        # 清理 1 秒之前的时间戳
        client.message_timestamps = [t for t in client.message_timestamps if now - t < 1.0]
        if len(client.message_timestamps) >= limit:
            return False
        client.message_timestamps.append(now)
        return True

    # ── 统计 ──────────────────────────────────────────────────────────────

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def team_connection_count(self, team_id: str) -> int:
        return len(self._team_index.get(team_id, set()))

    # ── 内部辅助方法 ───────────────────────────────────────────────────

    @staticmethod
    async def _safe_send(client: WSClient, message: dict[str, Any]) -> None:
        """发送 JSON 消息，忽略断连错误。"""
        try:
            if client.ws.client_state == WebSocketState.CONNECTED:
                await client.ws.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @staticmethod
    async def _safe_close(ws: WebSocket) -> None:
        """关闭 WebSocket，忽略错误。"""
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.close(code=1000)
        except (WebSocketDisconnect, RuntimeError):
            pass


# ── 单例 ──────────────────────────────────────────────────────────────────

ws_manager = ConnectionManager()
