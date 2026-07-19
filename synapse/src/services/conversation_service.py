"""A2A Conversation Service — 消息 CRUD + @mention 解析 + handoff 管道.

P10-B29: 议题 5 A2A 协议 — Service 层。

核心能力：
- create_message: 创建结构化协调消息 + @mention 解析 + handoff 自动创建 AuthorizationRequest
- get_message / list_messages: 消息查询（按 Task 聚合，游标分页）
- update_message: 编辑正文或标记 resolved（idempotent）

调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import EventType
from src.exceptions import NotFoundError
from src.models.task_worker_conversation import TaskWorkerConversation
from src.models.task import Task
from src.models.worker import Worker
from src.models.workflow import WorkflowRole
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ── @mention 解析 ───────────────────────────────────────────────────────

# 匹配 @worker:<name> 和 @role:<rolename>，name/rolename 不含空白字符
_MENTION_RE = re.compile(r"@(worker|role):(\S+)")


def parse_mentions(body: str) -> list[dict[str, str]]:
    """从消息正文解析 @mention 引用。

    返回去重后的 mention 列表，每项包含 type 和 value：
        [{"type": "worker", "value": "claude-builder"}, ...]

    解析失败时返回空列表 — 不抛异常，因为 mention 是辅助功能。
    """
    mentions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _MENTION_RE.finditer(body):
        mention_type = m.group(1)
        value = m.group(2)
        key = (mention_type, value)
        if key not in seen:
            seen.add(key)
            mentions.append({"type": mention_type, "value": value})
    return mentions


async def resolve_mentions(
    db: AsyncSession,
    mentions: list[dict[str, str]],
    workflow_id: str | None = None,
) -> list[str]:
    """将 @mention 引用解析为 worker_id 列表。

    - @worker:<name> → 模糊匹配 worker.name（case-insensitive LIKE）
    - @role:<rolename> → 在 Workflow 上下文中查找该角色的 Worker（需 workflow_id）

    无法解析的 mention 静默跳过 — 消息不因 mention 无效而创建失败。
    """
    worker_ids: list[str] = []
    seen: set[str] = set()

    worker_names: list[str] = []
    role_names: list[str] = []

    for mention in mentions:
        if mention["type"] == "worker":
            worker_names.append(mention["value"])
        elif mention["type"] == "role":
            role_names.append(mention["value"])

    # ── 解析 @worker:<name> ──
    if worker_names:
        # 每个 name 做 LIKE 匹配
        conditions = [
            Worker.name.ilike(f"%{name}%") for name in worker_names
        ]
        from sqlalchemy import or_

        result = await db.execute(
            select(Worker.id, Worker.name).where(or_(*conditions))
        )
        for row in result.all():
            wid = row[0]
            if wid not in seen:
                seen.add(wid)
                worker_ids.append(wid)

    # ── 解析 @role:<rolename> ──
    if role_names and workflow_id:
        result = await db.execute(
            select(WorkflowRole.worker_id)
            .where(
                WorkflowRole.workflow_id == workflow_id,
                WorkflowRole.role.in_(role_names),
            )
        )
        for row in result.all():
            wid = row[0]
            if wid is not None and wid not in seen:
                seen.add(wid)
                worker_ids.append(wid)

    return worker_ids


# ── 查询辅助 ────────────────────────────────────────────────────────────


async def get_message(
    db: AsyncSession,
    message_id: str,
) -> TaskWorkerConversation:
    """按 ID 获取消息，不存在则 raise NotFoundError。"""
    result = await db.execute(
        select(TaskWorkerConversation).where(
            TaskWorkerConversation.id == message_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("TaskWorkerConversation", message_id)
    return record


async def list_messages(
    db: AsyncSession,
    task_id: str,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[TaskWorkerConversation], str | None, int | None]:
    """按 Task 聚合消息列表，游标分页，按创建时间升序。

    返回 (items, next_cursor, total)。
    """
    conditions = [TaskWorkerConversation.task_id == task_id]
    if cursor:
        conditions.append(TaskWorkerConversation.id > cursor)

    stmt = (
        select(TaskWorkerConversation)
        .where(*conditions)
        .order_by(TaskWorkerConversation.created_at.asc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = (
        select(func.count(TaskWorkerConversation.id))
        .where(TaskWorkerConversation.task_id == task_id)
    )
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total


# ── 写入 ────────────────────────────────────────────────────────────────


async def create_message(
    db: AsyncSession,
    *,
    task_id: str,
    workflow_id: str | None,
    message_type: str,
    body: str,
    in_reply_to_id: str | None,
    sender_worker_id: str,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> TaskWorkerConversation:
    """创建 A2A 结构化协调消息。

    - 解析 @mention → mentions_json
    - 解析 @mention → worker_id 列表（用于通知/索引）
    - handoff 类型：自动创建 AuthorizationRequest 并链接

    Raises:
        NotFoundError: task_id 或 in_reply_to_id 指向不存在的记录
    """
    # ── 校验 Task 存在 ──
    task_result = await db.execute(select(Task.id, Task.project_id).where(Task.id == task_id))
    task_row = task_result.first()
    if task_row is None:
        raise NotFoundError("Task", task_id)

    task_project_id: str = task_row[1]

    # ── @mention 解析 ──
    mentions = parse_mentions(body)
    worker_ids = await resolve_mentions(db, mentions, workflow_id)
    mentions_json_str = json.dumps(mentions) if mentions else None

    now = datetime.now(timezone.utc)
    message_id = generate_id("task_worker_conversation")

    # ── handoff: 创建 AuthorizationRequest ──
    authorization_request_id: str | None = None
    if message_type == "handoff":
        authorization_request_id = await _create_handoff_auth_request(
            db,
            task_id=task_id,
            project_id=task_project_id,
            sender_worker_id=sender_worker_id,
            body=body,
            target_worker_ids=worker_ids,
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )

    # ── 创建消息 ──
    message = TaskWorkerConversation(
        id=message_id,
        task_id=task_id,
        workflow_id=workflow_id,
        sender_worker_id=sender_worker_id,
        message_type=message_type,
        body=body,
        mentions_json=mentions_json_str,
        in_reply_to_id=in_reply_to_id,
        authorization_request_id=authorization_request_id,
        is_resolved=False,
    )
    db.add(message)
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.CONVERSATION_MESSAGE_CREATED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="task_worker_conversation",
        target_id=message.id,
        payload={
            "task_id": task_id,
            "workflow_id": workflow_id,
            "message_type": message_type,
            "sender_worker_id": sender_worker_id,
            "has_mentions": len(mentions) > 0,
            "is_handoff": message_type == "handoff",
            "authorization_request_id": authorization_request_id,
        },
    )

    return message


async def update_message(
    db: AsyncSession,
    *,
    message_id: str,
    body: str | None = None,
    is_resolved: bool | None = None,
    resolved_by_worker_id: str | None = None,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> TaskWorkerConversation:
    """更新消息正文 或 标记已解决。

    - body 非 None → 更新正文 + 重新解析 @mentions
    - is_resolved True 且之前为 False → 记录 CONVERSATION_MESSAGE_RESOLVED 事件
    - is_resolved False → 撤销 resolved 状态（重新打开）

    已 resolved 的消息再次 resolve → idempotent（不重复记录事件）。

    Raises:
        NotFoundError: 消息不存在
    """
    message = await get_message(db, message_id)
    was_resolved = message.is_resolved

    if body is not None:
        message.body = body
        # 重新解析 @mentions
        mentions = parse_mentions(body)
        message.mentions_json = json.dumps(mentions) if mentions else None

    if is_resolved is not None and is_resolved != was_resolved:
        message.is_resolved = is_resolved
        if is_resolved:
            message.resolved_at = datetime.now(timezone.utc)
            message.resolved_by_worker_id = resolved_by_worker_id

            await event_store.record(
                db,
                event_type=EventType.CONVERSATION_MESSAGE_RESOLVED,
                team_id=team_id,
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="task_worker_conversation",
                target_id=message.id,
                payload={
                    "task_id": message.task_id,
                    "message_type": message.message_type,
                    "resolved_by_worker_id": resolved_by_worker_id,
                },
            )
        else:
            # 重新打开
            message.resolved_at = None
            message.resolved_by_worker_id = None

    await db.flush()
    return message


# ── handoff 管道 ────────────────────────────────────────────────────────


async def _create_handoff_auth_request(
    db: AsyncSession,
    *,
    task_id: str,
    project_id: str,
    sender_worker_id: str,
    body: str,
    target_worker_ids: list[str],
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> str:
    """为 handoff 消息创建关联的 AuthorizationRequest。

    使用 ``task.assign`` 操作类型 — Worker 请求将任务转交权限。
    不在此处做流控检查；让 AuthorizationRequest 自己的流控逻辑处理。

    Returns:
        新创建的 authorization_request ID。
    """
    from src.services.authorization_service import create_authorization_request

    # handoff 的 AuthorizationRequest 参数
    auth_req = await create_authorization_request(
        db,
        project_id=project_id,
        worker_id=sender_worker_id,
        request_type="api_auth",
        operation="task.assign",
        target_resource_type="task",
        target_resource_id=task_id,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        # handoff 默认 24h TTL — 比普通 API auth 更长
        ttl_seconds=86400,
    )

    return auth_req.id
