"""Shared helpers for API route handlers."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType
from src.exceptions import NotFoundError
from src.models.event import Event
from src.models.project import Project
from src.models.team import Team


# PFL-269: 历史改名迁移（B40 agent→worker · B10 member→human）漏迁 event.actor_type
# 字符串值，遗留脏值会拖垮整个事件端点。读取侧做遗留值映射，未知值 fallback system。
_LEGACY_ACTOR_TYPE_MAP = {"agent": "worker", "member": "human"}


def _coerce_actor_type(value: str | None) -> str:
    """将 Event.actor_type 归一为 ActorType 枚举值，容错遗留/未知脏值。"""
    if value is None:
        return ActorType.SYSTEM.value
    normalized = str(value).strip().lower()
    normalized = _LEGACY_ACTOR_TYPE_MAP.get(normalized, normalized)
    try:
        return ActorType(normalized).value
    except ValueError:
        return ActorType.SYSTEM.value  # 未知值 fallback


def event_to_response(event: Event) -> dict:
    """Convert an Event ORM object to a JSON-safe dict."""
    return {
        "id": event.id,
        "team_id": event.team_id,
        "event_type": event.event_type,
        "actor_type": _coerce_actor_type(event.actor_type),
        "actor_id": event.actor_id,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "payload": json.loads(event.payload) if isinstance(event.payload, str) else event.payload,
        "idempotency_key": event.idempotency_key,
        "create_user_id": event.create_user_id,
        "created_at": event.created_at,
    }


async def get_team_or_404(db: AsyncSession, team_id: str) -> Team:
    """Fetch a team by ID or raise NotFoundError."""
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFoundError("team", team_id)
    return team


async def get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    """Fetch a project by ID or raise NotFoundError."""
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)
    return project


def _parse_event_payload(evt) -> dict:
    """解析 Event.payload JSON 字符串为 dict（P14-B3）。

    payload 以 JSON 字符串存储（String column），返回解析后的 dict。
    """
    import json as _json

    raw = evt.payload or {}
    if isinstance(raw, str):
        try:
            return _json.loads(raw)
        except (_json.JSONDecodeError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}
def _events_to_error_summaries(events: list) -> list:
    """将 WORKER_ERROR_REPORTED Event 列表转为 ErrorReportSummary 列表（P14-B3）。

    解析 Event.payload JSON 并构造摘要对象。
    severity 过滤已下推到 SQL 层，此处不再做二次过滤。
    """
    summaries = []
    for evt in events:
        payload = _parse_event_payload(evt)
        from src.schemas.worker import ErrorReportSummary
        summaries.append(ErrorReportSummary(
            id=evt.id,
            error_type=payload.get("error_type", "unknown"),
            task_id=payload.get("task_id"),
            summary=payload.get("summary", ""),
            severity=payload.get("severity", "🔴"),
            created_at=evt.created_at,
        ))
    return summaries
