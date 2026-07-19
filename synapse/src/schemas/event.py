"""事件 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.constants import ActorType


class EventResponse(BaseModel):
    """Event 读取操作的响应体。"""

    id: str
    team_id: str
    event_type: str
    actor_type: ActorType
    actor_id: str
    target_type: str
    target_id: str
    payload: dict
    idempotency_key: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
