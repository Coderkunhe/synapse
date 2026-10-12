"""P10-B29: Conversation Service 层测试 — parse_mentions / resolve_mentions / CRUD / handoff."""

from __future__ import annotations

import pytest
from sqlalchemy import select
import pytest_asyncio

from src.constants import ActorType
from src.db import async_session_factory
from src.exceptions import NotFoundError
from src.models.task import Task
from src.models.worker import Worker
from src.models.project_actor_role import ProjectActorRole
from src.models.project import Project
from src.services.conversation_service import (
    count_unread_mentions, create_message, get_message, list_messages,
    list_mentions, parse_mentions, resolve_mentions, update_message,
)
from src.utils.id_gen import generate_id
from unittest.mock import AsyncMock


# ══ Fixtures ══

@pytest_asyncio.fixture
async def db_session():
    """每个测试一个独立数据库会话，测试结束回滚."""
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def actor_info(seed):
    """从 seed 数据中提取事件元信息."""
    return {
        "team_id": seed.team_id,
        "actor_type": ActorType.WORKER,
        "actor_id": seed.worker_id,
    }


@pytest.fixture
async def test_worker(db_session, seed):
    """创建一个测试用的 Worker."""
    worker = Worker(
        id=generate_id("worker"),
        name="Test Builder",
        team_id=seed.team_id,
        actor_type="agent",
        status="active",
        api_key_hash="",
    )
    db_session.add(worker)
    await db_session.commit()
    return worker.id


@pytest.fixture
async def test_worker_2(db_session, seed):
    """创建第二个测试 Worker — 用于 handoff 目标."""
    worker = Worker(
        id=generate_id("worker"),
        name="Claude Reviewer",
        team_id=seed.team_id,
        actor_type="agent",
        status="active",
        api_key_hash="",
    )
    db_session.add(worker)
    await db_session.commit()
    return worker.id


@pytest.fixture
async def test_project(db_session, seed):
    """创建一个测试用的 Project."""
    project = Project(
        id=generate_id("project"),
        name="Test Project",
        slug=f"test-project-{generate_id('project')[-8:]}",
        team_id=seed.team_id,
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.fixture
async def test_task(db_session, seed, test_project):
    """创建一个测试用的 Task."""
    task = Task(
        id=generate_id("task"),
        project_id=test_project,
        title="Test Task for A2A",
        status="pending",
    )
    db_session.add(task)
    await db_session.commit()
    return task.id


# ══ parse_mentions (unit, no DB) ══

class TestParseMentions:
    """@mention 语法解析 — 纯函数."""

    def test_single_worker_mention(self):
        """单 @worker:name."""
        mentions = parse_mentions("请 @worker:claude-builder 审查代码。")
        assert mentions == [{"type": "worker", "value": "claude-builder"}]

    def test_multiple_mentions_dedup(self):
        """多个 mention — 去重."""
        mentions = parse_mentions(
            "@worker:alice 和 @worker:bob 请协助，@worker:alice 负责最终审查。"
        )
        assert len(mentions) == 2
        assert {"type": "worker", "value": "alice"} in mentions
        assert {"type": "worker", "value": "bob"} in mentions

    def test_worker_and_role_mixed(self):
        """worker 和 role 混合."""
        mentions = parse_mentions(
            "请 @worker:builder 执行，然后 @role:orchestrator 验收。"
        )
        assert len(mentions) == 2
        assert {"type": "worker", "value": "builder"} in mentions
        assert {"type": "role", "value": "orchestrator"} in mentions

    def test_no_mentions(self):
        """无 mention 的纯文本."""
        mentions = parse_mentions("这是普通消息，没有 @mention。")
        assert mentions == []

    def test_empty_body(self):
        """空正文."""
        mentions = parse_mentions("")
        assert mentions == []

    def test_at_without_colon_ignored(self):
        """@ 后面是冒号才匹配 — 普通 @ 字符被忽略."""
        mentions = parse_mentions("用 @ 符号标记但不触发 mention。")
        assert mentions == []

    def test_at_with_colon_but_not_keyword(self):
        """@unknown:value 不匹配 — 只匹配 worker/role."""
        mentions = parse_mentions("@channel:everyone 注意安全。")
        assert mentions == []

    def test_mention_with_special_chars_in_name(self):
        """mention 值可包含连字符和下划线."""
        mentions = parse_mentions("@worker:claude-builder_v2")
        assert mentions == [{"type": "worker", "value": "claude-builder_v2"}]

    def test_trailing_punctuation_not_captured(self):
        """P17-B25：尾随标点不进 token —— `@role:builder,` 解析为 `builder` 而非 `builder,`."""
        # 半角逗号
        assert parse_mentions("@role:builder, 请协助") == [
            {"type": "role", "value": "builder"}
        ]
        # 半角句号
        assert parse_mentions("@worker:claude-builder.") == [
            {"type": "worker", "value": "claude-builder"}
        ]
        # 全角逗号/句号
        assert parse_mentions("@worker:alice，请协助。") == [
            {"type": "worker", "value": "alice"}
        ]

    def test_internal_dot_preserved(self):
        """名称中间的点保留（v1.2）—— 只剥尾随标点，不误伤中间点."""
        assert parse_mentions("@worker:v1.2 审查") == [
            {"type": "worker", "value": "v1.2"}
        ]


# ══ resolve_mentions (DB integration) ══

class TestResolveMentions:
    """@mention → worker_id 解析."""

    @pytest.mark.asyncio
    async def test_resolve_worker_by_name(self, db_session, test_worker):
        """@worker 按 name 模糊匹配 — Test Builder 匹配 'builder'."""
        worker_obj = await db_session.get(Worker, test_worker)
        mentions = [{"type": "worker", "value": "Builder"}]
        result = await resolve_mentions(db_session, mentions)
        assert test_worker in result

    @pytest.mark.asyncio
    async def test_resolve_worker_no_match(self, db_session):
        """不存在的 worker 名 → 静默跳过."""
        mentions = [{"type": "worker", "value": "nonexistent-worker-xyz"}]
        result = await resolve_mentions(db_session, mentions)
        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_role_with_project(
        self, db_session, test_project, test_worker
    ):
        """@role 在 project 上下文中解析."""
        # 给 test_worker 在 project 中分配 orchestrator 角色
        par = ProjectActorRole(
            id=generate_id("project_actor_role"),
            project_id=test_project,
            worker_id=test_worker,
            role="orchestrator",
        )
        db_session.add(par)
        await db_session.commit()

        mentions = [{"type": "role", "value": "orchestrator"}]
        result = await resolve_mentions(db_session, mentions, project_id=test_project)
        assert test_worker in result

    @pytest.mark.asyncio
    async def test_resolve_role_no_project_skipped(self, db_session):
        """无 project_id 时 @role 无法解析 → 静默跳过."""
        mentions = [{"type": "role", "value": "orchestrator"}]
        result = await resolve_mentions(db_session, mentions, project_id=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_role_no_match(self, db_session, test_project):
        """project 中存在但无匹配角色."""
        mentions = [{"type": "role", "value": "nonexistent-role"}]
        result = await resolve_mentions(db_session, mentions, project_id=test_project)
        assert result == []

    @pytest.mark.asyncio
    async def test_resolve_mixed_mentions(
        self, db_session, test_project, test_worker, test_worker_2
    ):
        """混合 @worker + @role 解析."""
        # role 分配
        par = ProjectActorRole(
            id=generate_id("project_actor_role"),
            project_id=test_project,
            worker_id=test_worker_2,
            role="reviewer",
        )
        db_session.add(par)
        await db_session.commit()

        mentions = [
            {"type": "worker", "value": "Builder"},       # → test_worker
            {"type": "role", "value": "reviewer"},        # → test_worker_2
        ]
        result = await resolve_mentions(db_session, mentions, project_id=test_project)
        assert test_worker in result
        assert test_worker_2 in result

    @pytest.mark.asyncio
    async def test_resolve_role_matches_multiple_workers(
        self, db_session, test_project, test_worker, test_worker_2
    ):
        """@role 点名整个角色 — 同 project 多个 builder 都命中."""
        for wid in (test_worker, test_worker_2):
            db_session.add(ProjectActorRole(
                id=generate_id("project_actor_role"),
                project_id=test_project,
                worker_id=wid,
                role="builder",
            ))
        await db_session.commit()

        mentions = [{"type": "role", "value": "builder"}]
        result = await resolve_mentions(db_session, mentions, project_id=test_project)
        assert test_worker in result
        assert test_worker_2 in result


# ══ create_message ══

class TestCreateMessage:
    """创建 A2A 消息 — @mention 解析 + handoff 管道."""

    @pytest.mark.asyncio
    async def test_create_clarification(self, db_session, test_task, test_worker, actor_info):
        """创建 clarification 类型消息."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="这个函数的错误处理逻辑在哪里？",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert msg.id.startswith("twc_")
        assert msg.message_type == "clarification"
        assert msg.body == "这个函数的错误处理逻辑在哪里？"
        assert msg.is_resolved is False
        assert msg.mentions_json is None
        assert msg.authorization_request_id is None

    @pytest.mark.asyncio
    async def test_create_blocking(self, db_session, test_task, test_worker, actor_info):
        """创建 blocking 类型消息."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="blocking",
            body="被 PR #342 的 API 变更阻塞。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert msg.message_type == "blocking"
        assert msg.is_resolved is False

    @pytest.mark.asyncio
    async def test_create_with_mentions(
        self, db_session, test_task, test_worker, actor_info
    ):
        """创建消息时 @mention 被解析并写入 mentions_json."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="review_request",
            body="@worker:claude-builder 请审查。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert msg.mentions_json is not None
        assert "claude-builder" in msg.mentions_json

    @pytest.mark.asyncio
    async def test_create_handoff_creates_auth_request(
        self, db_session, test_task, test_worker, actor_info
    ):
        """handoff 类型自动创建 AuthorizationRequest."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="handoff",
            body="将任务移交给 @worker:claude-reviewer。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert msg.message_type == "handoff"
        assert msg.authorization_request_id is not None
        assert msg.authorization_request_id.startswith("areq_")

        # 验证 AuthorizationRequest 确实被创建
        from src.models.authorization_request import AuthorizationRequest
        result = await db_session.execute(
            select(AuthorizationRequest).where(
                AuthorizationRequest.id == msg.authorization_request_id,
            )
        )
        auth_req = result.scalar_one_or_none()
        assert auth_req is not None
        assert auth_req.request_type == "api_auth"
        assert auth_req.operation == "task.assign"
        assert auth_req.target_resource_type == "task"
        assert auth_req.target_resource_id == test_task

    @pytest.mark.asyncio
    async def test_create_handoff_without_mentions(
        self, db_session, test_task, test_worker, actor_info
    ):
        """handoff 无 @mention 也可创建 — AuthRequest 仍然生成."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="handoff",
            body="交接这个任务，不需要指定目标。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert msg.message_type == "handoff"
        assert msg.authorization_request_id is not None

    @pytest.mark.asyncio
    async def test_create_task_not_found(self, db_session, test_worker, actor_info):
        """Task 不存在 → NotFoundError."""
        with pytest.raises(NotFoundError, match="Task"):
            await create_message(
                db_session,
                task_id="tsk_nonexistent",
                workflow_id=None,
                message_type="clarification",
                body="测试。",
                in_reply_to_id=None,
                sender_worker_id=test_worker,
                **actor_info,
            )

    @pytest.mark.asyncio
    async def test_create_with_in_reply_to(
        self, db_session, test_task, test_worker, actor_info
    ):
        """创建回复消息 — in_reply_to_id 被设置."""
        # 先创建一条原始消息
        original = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="原消息。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.flush()

        # 创建回复
        reply = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="这是回复。",
            in_reply_to_id=original.id,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert reply.in_reply_to_id == original.id

    @pytest.mark.asyncio
    async def test_events_recorded_on_create(
        self, db_session, test_task, test_worker, actor_info
    ):
        """创建消息会记录 EventStore 事件."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="事件测试。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        # 检查事件已记录
        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "task_worker_conversation",
                Event.target_id == msg.id,
            )
        )
        events = result.scalars().all()
        assert len(events) >= 1
        assert any(e.event_type == "conversation.message.created" for e in events)


# ══ get_message ══

class TestGetMessage:
    """单个消息查询."""

    @pytest.mark.asyncio
    async def test_get_existing(self, db_session, test_task, test_worker, actor_info):
        """获取存在的消息."""
        created = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="测试获取。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        fetched = await get_message(db_session, created.id)
        assert fetched.id == created.id
        assert fetched.body == "测试获取。"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db_session):
        """获取不存在的消息 → NotFoundError."""
        with pytest.raises(NotFoundError, match="TaskWorkerConversation"):
            await get_message(db_session, "twc_nonexistent")


# ══ list_messages ══

class TestListMessages:
    """按 Task 聚合消息列表."""

    @pytest.mark.asyncio
    async def test_list_empty(self, db_session, test_task):
        """空列表."""
        items, cursor, total = await list_messages(db_session, test_task)
        assert items == []
        assert cursor is None
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_with_messages(
        self, db_session, test_task, test_worker, actor_info
    ):
        """列出多条消息."""
        for i in range(3):
            await create_message(
                db_session,
                task_id=test_task,
                workflow_id=None,
                message_type="clarification",
                body=f"消息 {i}",
                in_reply_to_id=None,
                sender_worker_id=test_worker,
                **actor_info,
            )
        await db_session.commit()

        items, cursor, total = await list_messages(db_session, test_task)
        assert len(items) == 3
        assert total == 3
        assert cursor is None  # 3 < default limit 50

    @pytest.mark.asyncio
    async def test_list_pagination(
        self, db_session, test_task, test_worker, actor_info
    ):
        """游标分页."""
        msg_ids = []
        for i in range(5):
            msg = await create_message(
                db_session,
                task_id=test_task,
                workflow_id=None,
                message_type="clarification",
                body=f"分页消息 {i}",
                in_reply_to_id=None,
                sender_worker_id=test_worker,
                **actor_info,
            )
            msg_ids.append(msg.id)
        await db_session.commit()

        # 第一页: limit=2
        page1, cursor1, total = await list_messages(db_session, test_task, limit=2)
        assert len(page1) == 2
        assert total == 5
        assert cursor1 is not None

        # 第二页
        page2, cursor2, _ = await list_messages(
            db_session, test_task, cursor=cursor1, limit=2
        )
        assert len(page2) == 2

        # 第三页（最后 1 条）
        page3, cursor3, _ = await list_messages(
            db_session, test_task, cursor=cursor2, limit=2
        )
        assert len(page3) == 1
        assert cursor3 is None

    @pytest.mark.asyncio
    async def test_list_isolated_by_task(
        self, db_session, test_task, test_worker, test_project, actor_info, seed
    ):
        """不同 Task 的消息互相隔离."""
        # 创建第二个 Task
        task2 = Task(
            id=generate_id("task"),
            project_id=test_project,
            title="Task 2",
            status="pending",
        )
        db_session.add(task2)
        await db_session.commit()

        # 在 task2 中创建消息
        await create_message(
            db_session,
            task_id=task2.id,
            workflow_id=None,
            message_type="clarification",
            body="Task 2 的消息。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        # task1 应不受影响
        items, _, total = await list_messages(db_session, test_task)
        assert total == 0


# ══ update_message ══

class TestUpdateMessage:
    """更新消息 — 编辑正文 + 标记 resolved."""

    @pytest.mark.asyncio
    async def test_update_body(self, db_session, test_task, test_worker, actor_info):
        """编辑正文."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="原始正文。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        updated = await update_message(
            db_session,
            message_id=msg.id,
            body="更新后的正文。",
            **actor_info,
        )
        await db_session.commit()

        assert updated.body == "更新后的正文。"
        assert updated.is_resolved is False

    @pytest.mark.asyncio
    async def test_update_body_reparses_mentions(
        self, db_session, test_task, test_worker, actor_info
    ):
        """编辑正文时重新解析 @mention."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="无 mention。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()
        assert msg.mentions_json is None

        updated = await update_message(
            db_session,
            message_id=msg.id,
            body="@worker:alice 来看一下。",
            **actor_info,
        )
        await db_session.commit()

        assert updated.mentions_json is not None
        assert "alice" in updated.mentions_json

    @pytest.mark.asyncio
    async def test_mark_resolved(self, db_session, test_task, test_worker, actor_info):
        """标记 resolved — 记录事件."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="blocking",
            body="被阻塞了。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()
        assert msg.is_resolved is False

        updated = await update_message(
            db_session,
            message_id=msg.id,
            is_resolved=True,
            resolved_by_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert updated.is_resolved is True
        assert updated.resolved_at is not None
        assert updated.resolved_by_worker_id == test_worker

        # 验证事件已记录
        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "task_worker_conversation",
                Event.target_id == msg.id,
                Event.event_type == "conversation.message.resolved",
            )
        )
        assert result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_resolve_idempotent(
        self, db_session, test_task, test_worker, actor_info
    ):
        """已 resolved 的消息再次 resolve → idempotent."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="blocking",
            body="阻塞消息。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        # 第一次 resolve
        updated1 = await update_message(
            db_session,
            message_id=msg.id,
            is_resolved=True,
            resolved_by_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()
        assert updated1.is_resolved is True

        # 第二次 resolve — 不应重复记录事件
        updated2 = await update_message(
            db_session,
            message_id=msg.id,
            is_resolved=True,
            resolved_by_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()
        assert updated2.is_resolved is True

        # 检查事件只记录了 1 次
        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "task_worker_conversation",
                Event.target_id == msg.id,
                Event.event_type == "conversation.message.resolved",
            )
        )
        assert len(result.scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_reopen_resolved(self, db_session, test_task, test_worker, actor_info):
        """reopen — 撤销 resolved 状态."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="blocking",
            body="阻塞了。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        # resolve
        await update_message(
            db_session,
            message_id=msg.id,
            is_resolved=True,
            resolved_by_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        # reopen
        reopened = await update_message(
            db_session,
            message_id=msg.id,
            is_resolved=False,
            **actor_info,
        )
        await db_session.commit()

        assert reopened.is_resolved is False
        assert reopened.resolved_at is None
        assert reopened.resolved_by_worker_id is None

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db_session, actor_info):
        """更新不存在的消息 → NotFoundError."""
        with pytest.raises(NotFoundError, match="TaskWorkerConversation"):
            await update_message(
                db_session,
                message_id="twc_nonexistent",
                body="新正文",
                **actor_info,
            )


# ══ mention 投递（S-020 · P17-B8） ══

class TestCreateMessageDelivery:
    """create_message 对被 @ 的 worker 精确 WS 投递."""

    @pytest.mark.asyncio
    async def test_mention_triggers_actor_broadcast(
        self, db_session, test_task, test_worker, test_worker_2, actor_info, monkeypatch
    ):
        """body 含 @worker:<name> → 被解析到的 worker 收到 event 信封推送."""
        broadcast_mock = AsyncMock()
        monkeypatch.setattr(
            "src.services.ws_manager.ws_manager.broadcast_to_actor", broadcast_mock
        )

        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="@worker:Claude 请审查这个改动。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        assert msg.mentions_json is not None
        called_ids = [call.args[0] for call in broadcast_mock.call_args_list]
        assert test_worker_2 in called_ids

        # 信封必须是 {"type": "event", "data": {...}}（前端 ws.ts 只认 type==='event'）
        for call in broadcast_mock.call_args_list:
            assert call.args[1]["type"] == "event"
            assert call.args[1]["data"]["event_type"] == "conversation.message.created"

    @pytest.mark.asyncio
    async def test_no_mention_no_broadcast(
        self, db_session, test_task, test_worker, actor_info, monkeypatch
    ):
        """无 @mention → 不触发 actor 投递."""
        broadcast_mock = AsyncMock()
        monkeypatch.setattr(
            "src.services.ws_manager.ws_manager.broadcast_to_actor", broadcast_mock
        )

        await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="普通消息，无 mention。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        broadcast_mock.assert_not_called()


# ══ mention 落库 + 未读查询（P17-B12） ══

class TestMentionPersistence:
    """create_message 把解析出的 worker_id 落关联表."""

    @pytest.mark.asyncio
    async def test_create_message_persists_mentions(
        self, db_session, test_task, test_worker, test_worker_2, actor_info
    ):
        """body 含 @worker → 关联表落一条 (conversation_id, worker_id)."""
        from src.models.task_worker_conversation import TaskWorkerConversationMention

        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="@worker:Claude 请审查。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        result = await db_session.execute(
            select(TaskWorkerConversationMention).where(
                TaskWorkerConversationMention.conversation_id == msg.id,
            )
        )
        rows = result.scalars().all()
        assert test_worker_2 in [r.worker_id for r in rows]
        assert test_worker not in [r.worker_id for r in rows]  # sender 自身不落

    @pytest.mark.asyncio
    async def test_no_mention_no_persistence(
        self, db_session, test_task, test_worker, actor_info
    ):
        """无 @mention → 不落关联表."""
        from src.models.task_worker_conversation import TaskWorkerConversationMention

        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="普通消息。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        result = await db_session.execute(
            select(TaskWorkerConversationMention).where(
                TaskWorkerConversationMention.conversation_id == msg.id,
            )
        )
        assert result.scalars().all() == []


class TestListMentions:
    """未读 mention 查询 — 未读语义（决策 3）."""

    @pytest.mark.asyncio
    async def test_mention_is_unread(
        self, db_session, test_task, test_worker, test_worker_2, actor_info
    ):
        """指向 worker 且未回复 → 未读."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="@worker:Claude 请审查。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        items = await list_mentions(db_session, test_worker_2)
        assert msg.id in [m.id for m in items]
        assert await count_unread_mentions(db_session, test_worker_2) == 1

    @pytest.mark.asyncio
    async def test_non_reply_message_does_not_mark_read(
        self, db_session, test_task, test_worker, test_worker_2, actor_info
    ):
        """worker 发过非回复消息（in_reply_to_id=None）→ mention 仍判未读（PFL-277）."""
        # test_worker_2 先发一条非回复消息，其 in_reply_to_id 为 NULL，
        # 用于复现 PFL-277：replied 子查询含 NULL 时 NOT IN 恒为 NULL。
        await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="这是一条非回复消息，in_reply_to_id 为 NULL。",
            in_reply_to_id=None,
            sender_worker_id=test_worker_2,
            **actor_info,
        )
        await db_session.commit()

        # test_worker @ test_worker_2
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="@worker:Claude 请审查。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        items = await list_mentions(db_session, test_worker_2)
        assert msg.id in [m.id for m in items]
        assert await count_unread_mentions(db_session, test_worker_2) == 1

    @pytest.mark.asyncio
    async def test_reply_marks_read(
        self, db_session, test_task, test_worker, test_worker_2, actor_info
    ):
        """worker in_reply_to 回复后 → 已读（从未读列表消失）."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="@worker:Claude 请审查。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        # test_worker_2 回复
        await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="收到，这就看。",
            in_reply_to_id=msg.id,
            sender_worker_id=test_worker_2,
            **actor_info,
        )
        await db_session.commit()

        items = await list_mentions(db_session, test_worker_2)
        assert msg.id not in [m.id for m in items]
        assert await count_unread_mentions(db_session, test_worker_2) == 0

    @pytest.mark.asyncio
    async def test_self_mention_excluded(
        self, db_session, test_task, test_worker, actor_info
    ):
        """自 @ → 不列入未读."""
        await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="@worker:Builder 记录给自己看。",  # test_worker name="Test Builder"
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        items = await list_mentions(db_session, test_worker)
        assert items == []
        assert await count_unread_mentions(db_session, test_worker) == 0

    @pytest.mark.asyncio
    async def test_project_filter(
        self, db_session, test_task, test_project, test_worker, test_worker_2, actor_info
    ):
        """project_id 过滤：正确 project 命中 · 错误 project 空."""
        msg = await create_message(
            db_session,
            task_id=test_task,
            workflow_id=None,
            message_type="clarification",
            body="@worker:Claude 请审查。",
            in_reply_to_id=None,
            sender_worker_id=test_worker,
            **actor_info,
        )
        await db_session.commit()

        items = await list_mentions(db_session, test_worker_2, project_id=test_project)
        assert msg.id in [m.id for m in items]

        items_wrong = await list_mentions(
            db_session, test_worker_2, project_id="prj_nonexistent"
        )
        assert items_wrong == []


# ══ mention 级联删除（PFL-276 / P100-B180） ══

class TestMentionCascade:
    """mention 关联行随 worker / conversation 删除级联清理."""

    async def _make_mention(self, db_session, test_task, test_worker, test_worker_2):
        """直接构造一条消息 + 一条指向 test_worker_2 的 mention 行。

        不走 create_message（其 resolve_mentions 用 name LIKE 匹配，历史同名
        worker 会干扰精确断言）。返回 (msg, mention)。
        """
        from src.models.task_worker_conversation import (
            TaskWorkerConversation,
            TaskWorkerConversationMention,
        )

        msg = TaskWorkerConversation(
            id=generate_id("task_worker_conversation"),
            task_id=test_task,
            sender_worker_id=test_worker,
            message_type="clarification",
            body="@worker:Claude 请审查。",
        )
        mention = TaskWorkerConversationMention(
            id=generate_id("task_worker_conversation_mention"),
            conversation_id=msg.id,
            worker_id=test_worker_2,
        )
        db_session.add_all([msg, mention])
        await db_session.commit()
        return msg, mention

    @pytest.mark.asyncio
    async def test_mention_cascade_on_worker_delete(
        self, db_session, test_task, test_worker, test_worker_2
    ):
        """删除被 @ 的 worker → 指向它的 mention 行级联删除（此前 FK 无 CASCADE 报 500）."""
        from src.models.task_worker_conversation import TaskWorkerConversationMention

        _, mention = await self._make_mention(
            db_session, test_task, test_worker, test_worker_2
        )

        # 删除被 @ 的 worker → 指向它的 mention 行随 FK CASCADE 清理
        target = await db_session.get(Worker, test_worker_2)
        await db_session.delete(target)
        await db_session.commit()

        remaining = await db_session.execute(
            select(TaskWorkerConversationMention).where(
                TaskWorkerConversationMention.id == mention.id,
            )
        )
        assert remaining.scalars().all() == []

    @pytest.mark.asyncio
    async def test_mention_cascade_on_conversation_delete(
        self, db_session, test_task, test_worker, test_worker_2
    ):
        """删除消息 → 其 mention 关联行级联删除."""
        from src.models.task_worker_conversation import (
            TaskWorkerConversation,
            TaskWorkerConversationMention,
        )

        msg, mention = await self._make_mention(
            db_session, test_task, test_worker, test_worker_2
        )

        # 删除消息 → mention 行随 FK CASCADE 清理
        conv = await db_session.get(TaskWorkerConversation, msg.id)
        await db_session.delete(conv)
        await db_session.commit()

        remaining = await db_session.execute(
            select(TaskWorkerConversationMention).where(
                TaskWorkerConversationMention.id == mention.id,
            )
        )
        assert remaining.scalars().all() == []
