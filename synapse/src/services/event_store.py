"""写穿式事件记录服务。

所有状态变更操作必须调用 event_store.record()。
事件只追加 — 不可更新、不可删除。
调用方持有事务：状态变更和事件写入一起成功或一起失败。

记录后，事件通过 ws_manager.broadcast_to_team() 以 fire-and-forget
方式向 WebSocket 订阅者广播。
"""

import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.event import Event
from src.utils.id_gen import generate_id
from src.constants import ActorType


class EventStore:
    """集中式事件记录，支持幂等和查询方法。

    在路由处理器中的用法：
        await event_store.record(
            db,
            event_type="task.assigned",
            team_id=team_id,
            actor_type=ActorType.HUMAN,
            actor_id=member_id,
            target_type="task",
            target_id=task_id,
            payload={"changes": {...}, "snapshot": {...}},
        )
        await db.commit()  # 调用方持有事务
    """

    # ── 写入 ──────────────────────────────────────────────────────

    async def record(
        self,
        db: AsyncSession,
        *,
        event_type: str,
        team_id: str,
        actor_type: str,
        actor_id: str,
        target_type: str,
        target_id: str,
        payload: dict,
        idempotency_key: str | None = None,
    ) -> Event:
        """记录不可变事件。返回创建的 Event。

        如果提供了 idempotency_key 且已存在，则返回已有事件而非创建重复事件。
        """
        # 幂等检查
        if idempotency_key:
            result = await db.execute(
                select(Event).where(Event.idempotency_key == idempotency_key)
            )
            if existing := result.scalar_one_or_none():
                return existing

        event = Event(
            id=generate_id("event"),
            team_id=team_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            payload=json.dumps(payload),
            idempotency_key=idempotency_key,
        )
        db.add(event)

        # Fire-and-forget：向 WebSocket 订阅者广播
        _broadcast_event(team_id, event)

        return event

    # ── 查询 ──────────────────────────────────────────────────────

    async def query_team_events(
        self,
        db: AsyncSession,
        team_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Event], str | None, int | None]:
        """游标分页列出团队事件，最新优先。"""
        conditions = [Event.team_id == team_id]
        if cursor:
            conditions.append(Event.id > cursor)

        stmt = (
            select(Event)
            .where(*conditions)
            .order_by(Event.created_at.desc())
            .limit(limit + 1)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = items[-1].id if has_more and items else None

        count_stmt = select(func.count(Event.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar()

        return items, next_cursor, total

    async def query_project_events(
        self,
        db: AsyncSession,
        *,
        team_id: str,
        task_ids: list[str],
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Event], str | None]:
        """游标分页列出项目事件（限定在其任务范围内）。

        返回 (items, next_cursor)。不含总数 — 项目事件通过任务 ID
        子查询过滤，对大项目而言计数代价高昂。
        """
        conditions = [
            Event.team_id == team_id,
            Event.target_id.in_(task_ids),
        ]
        if cursor:
            conditions.append(Event.id > cursor)

        stmt = (
            select(Event)
            .where(*conditions)
            .order_by(Event.created_at.desc())
            .limit(limit + 1)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = items[-1].id if has_more and items else None

        return items, next_cursor


# 模块级单例，用于依赖注入
event_store = EventStore()


# ── WebSocket 广播钩子 ────────────────────────────────────────────────


def _broadcast_event(team_id: str, event: Event) -> None:
    """Fire-and-forget 方式将新记录的事件广播给 WebSocket 客户端。

    作为后台任务运行以避免阻塞 HTTP 响应。
    失败静默忽略 — WebSocket 是尽力推送；
    客户端始终可以回退到 REST 轮询。
    """
    from src.services.ws_manager import ws_manager

    event_dict = {
        "id": event.id,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "payload": json.loads(event.payload) if isinstance(event.payload, str) else event.payload,
        "team_id": event.team_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }

    # 将广播作为后台任务调度 — 不阻塞调用方
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.broadcast_to_team(team_id, event_dict))
    except RuntimeError:
        # 无运行中的事件循环（如测试或同步上下文）— 跳过
        pass
