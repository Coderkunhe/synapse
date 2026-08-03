"""A2A Conversation Message API 端点 — Worker 间结构化协调消息。

P10-B30: 议题 5 A2A 协议 — API 路由层。

端点挂载在 ``/v1/projects/{project_id}/tasks/{task_id}/messages`` 下，
使用 ``require_permission("task:comment")`` 守卫。
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo
from src.permissions import require_permission

from src.schemas.task_worker_conversation import (
    ConversationMessageCreate,
    ConversationMessageResponse,
    ConversationMessageUpdate,
)
from src.services.conversation_service import (
    create_message,
    get_message,
    list_messages,
    update_message,
)

from .helpers import get_project_or_404

router = APIRouter()


# ── Inline response models ─────────────────────────────────────────


class ConversationMessageList(BaseModel):
    """Response wrapper for message listing with pagination."""
    task_id: str
    messages: list[ConversationMessageResponse]
    next_cursor: str | None = None
    total: int | None = None


# ═══════════════════════════════════════════════════════════════════
# CRUD 端点
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "",
    response_model=ConversationMessageResponse,
    status_code=201,
)
async def create_message_endpoint(
    project_id: str,
    task_id: str,
    body: ConversationMessageCreate,
    actor: ActorInfo = Depends(require_permission("task:comment")),
    db: AsyncSession = Depends(get_db),
):
    """Create a structured coordination message in a Task context.

    Supports @worker:name and @role:rolename mentions.
    Handoff messages (message_type=handoff) automatically create
    an associated AuthorizationRequest.
    """
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    message = await create_message(
        db,
        task_id=task_id,
        workflow_id=body.workflow_id,
        message_type=body.message_type,
        body=body.body,
        in_reply_to_id=body.in_reply_to_id,
        sender_worker_id=actor.actor_id,
        proposal_status=body.proposal_status,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return _msg_to_response(message)


@router.get(
    "",
    response_model=ConversationMessageList,
)
async def list_messages_endpoint(
    project_id: str,
    task_id: str,
    cursor: str | None = Query(None, description="Pagination cursor (message ID)"),
    limit: int = Query(50, ge=1, le=100, description="Max messages per page"),
    actor: ActorInfo = Depends(require_permission("task:comment")),
    db: AsyncSession = Depends(get_db),
):
    """List coordination messages for a Task, ordered by creation time (ascending).

    Cursor-based pagination — pass the last message ID as ``cursor``
    to get the next page.
    """
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    items, next_cursor, total = await list_messages(
        db,
        task_id,
        cursor=cursor,
        limit=limit,
    )

    return ConversationMessageList(
        task_id=task_id,
        messages=[_msg_to_response(m) for m in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get(
    "/{message_id}",
    response_model=ConversationMessageResponse,
)
async def get_message_endpoint(
    project_id: str,
    task_id: str,
    message_id: str,
    actor: ActorInfo = Depends(require_permission("task:comment")),
    db: AsyncSession = Depends(get_db),
):
    """Get a single coordination message by ID."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    message = await get_message(db, message_id)
    if message.task_id != task_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("TaskWorkerConversation", message_id)

    return _msg_to_response(message)


@router.patch(
    "/{message_id}",
    response_model=ConversationMessageResponse,
)
async def update_message_endpoint(
    project_id: str,
    task_id: str,
    message_id: str,
    body: ConversationMessageUpdate,
    actor: ActorInfo = Depends(require_permission("task:comment")),
    db: AsyncSession = Depends(get_db),
):
    """Update a message body or mark it resolved.

    - Set ``is_resolved: true`` to mark as resolved (idempotent).
    - Set ``is_resolved: false`` to reopen a resolved message.
    - Set ``body`` to edit the message content.
    """
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    # Verify message belongs to this task
    message = await get_message(db, message_id)
    if message.task_id != task_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("TaskWorkerConversation", message_id)

    updated = await update_message(
        db,
        message_id=message_id,
        body=body.body,
        is_resolved=body.is_resolved,
        resolved_by_worker_id=actor.actor_id if body.is_resolved else None,
        proposal_status=body.proposal_status,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return _msg_to_response(updated)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _msg_to_response(msg) -> ConversationMessageResponse:
    """Convert ORM TaskWorkerConversation to ConversationMessageResponse."""
    return ConversationMessageResponse.model_validate(msg)
