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

from src.constants import AuthorizationOperation, EventType
from src.exceptions import NotFoundError
from src.models.task_worker_conversation import (
    TaskWorkerConversation,
    TaskWorkerConversationMention,
)
from src.models.task import Task
from src.models.worker import Worker
from src.models.project_actor_role import ProjectActorRole
from src.services.event_store import event_store, event_to_dict
from src.utils.id_gen import generate_id


# ── @mention 解析 ───────────────────────────────────────────────────────

# 匹配 @worker:<name> 和 @role:<rolename>。
# name/rolename 由 [A-Za-z0-9_.-] 组成且须以字母/数字/下划线结尾 —— 尾随标点（逗号/句号/全角标点）不进 token。
# 与前端 MENTION_RE（TaskDetail.tsx:22）逐字符一致，保证「高亮范围 == 解析范围」契约不破（B15）。
_MENTION_RE = re.compile(r"@(worker|role):([A-Za-z0-9_.-]*[A-Za-z0-9_])")


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
    project_id: str | None = None,
) -> list[str]:
    """将 @mention 引用解析为 worker_id 列表。

    - @worker:<name> → 模糊匹配 worker.name（case-insensitive LIKE）
    - @role:<rolename> → 在 Project 上下文中查找该角色的 Worker（需 project_id）

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
    if role_names and project_id:
        result = await db.execute(
            select(ProjectActorRole.worker_id)
            .where(
                ProjectActorRole.project_id == project_id,
                ProjectActorRole.role.in_(role_names),
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


# ── mention 未读查询（P17-B12）──────────────────────────────────────


async def list_mentions(
    db: AsyncSession,
    worker_id: str,
    *,
    project_id: str | None = None,
    limit: int = 50,
    unread: bool = True,
) -> list[TaskWorkerConversation]:
    """列出指向 worker 的 mention。

    ``unread=True``（默认）：未读判定（决策 3）——mention 指向该 worker，且该
    worker 尚未以 ``in_reply_to`` 回复该条 mention，且非该 worker 自 @。
    ``unread=False``：返回所有指向该 worker 的 mention（含已回复 / 自 @）。
    """
    stmt = (
        select(TaskWorkerConversation)
        .join(
            TaskWorkerConversationMention,
            TaskWorkerConversationMention.conversation_id == TaskWorkerConversation.id,
        )
        .where(TaskWorkerConversationMention.worker_id == worker_id)
    )
    if unread:
        replied = (
            select(TaskWorkerConversation.in_reply_to_id)
            .where(TaskWorkerConversation.sender_worker_id == worker_id)
            .where(TaskWorkerConversation.in_reply_to_id.isnot(None))
        )
        stmt = (
            stmt.where(TaskWorkerConversation.sender_worker_id != worker_id)
            .where(TaskWorkerConversation.id.notin_(replied))
        )
    stmt = stmt.order_by(TaskWorkerConversation.created_at.asc())
    if project_id is not None:
        stmt = stmt.join(Task, Task.id == TaskWorkerConversation.task_id).where(
            Task.project_id == project_id
        )
    result = await db.execute(stmt.limit(limit))
    return list(result.scalars().all())


async def count_unread_mentions(
    db: AsyncSession,
    worker_id: str,
    *,
    project_id: str | None = None,
) -> int:
    """未读 mention 计数（state_router 心跳轮询复用 · B13）。"""
    replied = (
        select(TaskWorkerConversation.in_reply_to_id)
        .where(TaskWorkerConversation.sender_worker_id == worker_id)
        .where(TaskWorkerConversation.in_reply_to_id.isnot(None))
    )
    stmt = (
        select(func.count(TaskWorkerConversation.id))
        .join(
            TaskWorkerConversationMention,
            TaskWorkerConversationMention.conversation_id == TaskWorkerConversation.id,
        )
        .where(TaskWorkerConversationMention.worker_id == worker_id)
        .where(TaskWorkerConversation.sender_worker_id != worker_id)
        .where(TaskWorkerConversation.id.notin_(replied))
    )
    if project_id is not None:
        stmt = stmt.join(Task, Task.id == TaskWorkerConversation.task_id).where(
            Task.project_id == project_id
        )
    return int((await db.execute(stmt)).scalar() or 0)


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
    proposal_status: str | None = None,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> TaskWorkerConversation:
    """创建 A2A 结构化协调消息。

    - 解析 @mention → mentions_json
    - 解析 @mention → worker_id 列表（用于通知/索引）
    - handoff 类型：自动创建 AuthorizationRequest 并链接
    - proposal 类型：记录 proposal_status 追踪 O 提案→Human 确认 (P11-B117)

    Raises:
        NotFoundError: task_id 或 in_reply_to_id 指向不存在的记录
    """
    # ── 校验 Task 存在 ──
    task_result = await db.execute(select(Task.id, Task.project_id).where(Task.id == task_id))
    task_row = task_result.first()
    if task_row is None:
        raise NotFoundError("Task", task_id)

    task_project_id: str = task_row[1]

    # ── P12-B49: FK 前置校验 — 在 INSERT 前验证引用完整性，
    #     将 IntegrityError 500 转换为明确的 404/422 ──
    if in_reply_to_id is not None:
        reply_result = await db.execute(
            select(TaskWorkerConversation.id).where(
                TaskWorkerConversation.id == in_reply_to_id,
            ),
        )
        if reply_result.first() is None:
            raise NotFoundError("TaskWorkerConversation", in_reply_to_id)

    if workflow_id is not None:
        from src.models.workflow import Workflow
        wf_result = await db.execute(
            select(Workflow.id).where(Workflow.id == workflow_id),
        )
        if wf_result.first() is None:
            raise NotFoundError("Workflow", workflow_id)

    if sender_worker_id is not None:
        from src.models.worker import Worker
        sw_result = await db.execute(
            select(Worker.id).where(Worker.id == sender_worker_id),
        )
        if sw_result.first() is None:
            raise NotFoundError("Worker", sender_worker_id)

    # ── @mention 解析 ──
    mentions = parse_mentions(body)
    worker_ids = await resolve_mentions(db, mentions, task_project_id)
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
        proposal_status=proposal_status,
    )
    db.add(message)
    await db.flush()

    # ── P17-B12: mention 落库（可索引 worker 维度查询）────────────
    # resolve_mentions 结果此前只用于 WS 投递、不回写存储 → 每次查「谁被 @」
    # 都要重跑 name LIKE。这里落关联表，让「按 worker 查未读 mention」可索引。
    for wid in worker_ids:
        db.add(TaskWorkerConversationMention(
            id=generate_id("task_worker_conversation_mention"),
            conversation_id=message_id,
            worker_id=wid,
        ))

    event = await event_store.record(
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

    # ── mention 投递（S-020 · P17-B8）────────────────────────────
    # team 广播（event_store 内部）依赖客户端订阅 conversation.message.created，
    # 而 agent worker 未必订阅 → 这里按 resolve_mentions 结果精确送达被 @ 的 worker。
    if worker_ids:
        from src.services.ws_manager import ws_manager

        event_dict = event_to_dict(event)
        for wid in worker_ids:
            await ws_manager.broadcast_to_actor(wid, {"type": "event", "data": event_dict})

    return message


async def update_message(
    db: AsyncSession,
    *,
    message_id: str,
    body: str | None = None,
    is_resolved: bool | None = None,
    resolved_by_worker_id: str | None = None,
    proposal_status: str | None = None,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> TaskWorkerConversation:
    """更新消息正文、标记已解决、或更新提案状态。

    - body 非 None → 更新正文 + 重新解析 @mentions
    - is_resolved True 且之前为 False → 记录 CONVERSATION_MESSAGE_RESOLVED 事件
    - is_resolved False → 撤销 resolved 状态（重新打开）
    - proposal_status 非 None → 更新提案状态 (P11-B117 PFL-113)

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

    if proposal_status is not None:
        message.proposal_status = proposal_status

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

    PFL-074 (B121): 若 handoff 目标包含 Orchestrator，跳过 auth request。
    Orchestrator 本就拥有 task assign 权限——创建 auth request 是多余的，
    且会静默挂起等待 Human 审批（见 PFL-074 14h 悬挂案例）。

    Returns:
        新创建的 authorization_request ID，或 None（当目标为 Orchestrator 时跳过）。
    """
    from src.models.project_actor_role import ProjectActorRole
    from src.services.authorization_service import create_authorization_request

    # PFL-074: 若 handoff 目标是 Orchestrator → 跳过 auth request
    # O 拥有 task assign 权限，创建 auth request 只会产生无人关注的悬挂审批
    if target_worker_ids:
        orchestrator_result = await db.execute(
            select(ProjectActorRole.worker_id).where(
                ProjectActorRole.project_id == project_id,
                ProjectActorRole.worker_id.in_(target_worker_ids),
                ProjectActorRole.role == "orchestrator",
            ).limit(1)
        )
        if orchestrator_result.scalar_one_or_none() is not None:
            # Target is Orchestrator — O already has assign authority, skip
            return None

    # handoff 的 AuthorizationRequest 参数
    auth_req = await create_authorization_request(
        db,
        project_id=project_id,
        worker_id=sender_worker_id,
        request_type="api_auth",
        operation=AuthorizationOperation.TASK_ASSIGN,
        target_resource_type="task",
        target_resource_id=task_id,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        # handoff 默认 24h TTL — 比普通 API auth 更长
        ttl_seconds=86400,
    )

    return auth_req.id
