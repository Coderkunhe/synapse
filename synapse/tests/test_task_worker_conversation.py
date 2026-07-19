"""P10-B28: TaskWorkerConversation 模型 + Schema 基础测试。"""

import pytest
from pydantic import ValidationError

from src.models.task_worker_conversation import TaskWorkerConversation
from src.schemas.task_worker_conversation import (
    ConversationMessageCreate,
    ConversationMessageUpdate,
    ConversationMessageResponse,
)


# ═════════════════════════════════════════════════════════════════════════
# Schema: ConversationMessageCreate
# ═════════════════════════════════════════════════════════════════════════


class TestConversationMessageCreate:
    """创建 A2A 消息 schema 校验。"""

    def test_clarification_minimal(self):
        """clarification 类型最小字段。"""
        msg = ConversationMessageCreate(
            task_id="tsk_test1234",
            message_type="clarification",
            body="这个函数的错误处理逻辑在哪里？",
        )
        assert msg.message_type == "clarification"
        assert msg.task_id == "tsk_test1234"
        assert msg.workflow_id is None
        assert msg.in_reply_to_id is None

    def test_blocking_with_workflow(self):
        """blocking 类型含 workflow 上下文。"""
        msg = ConversationMessageCreate(
            task_id="tsk_test1234",
            workflow_id="wfl_test5678",
            message_type="blocking",
            body="被 PR #342 的 API 变更阻塞，等待合并。",
        )
        assert msg.message_type == "blocking"
        assert msg.workflow_id == "wfl_test5678"

    def test_review_request(self):
        """review_request 类型。"""
        msg = ConversationMessageCreate(
            task_id="tsk_test1234",
            message_type="review_request",
            body="@worker:claude-builder 请审查认证模块的重构。",
        )
        assert msg.message_type == "review_request"

    def test_handoff_full(self):
        """handoff 类型完整字段 — 含 in_reply_to 线程。"""
        msg = ConversationMessageCreate(
            task_id="tsk_test1234",
            workflow_id="wfl_test5678",
            message_type="handoff",
            body="将任务移交给 @worker:gpt-builder，需要数据库迁移经验。",
            in_reply_to_id="twc_prev_msg",
        )
        assert msg.message_type == "handoff"
        assert msg.in_reply_to_id == "twc_prev_msg"

    def test_invalid_message_type_rejected(self):
        """非法 message_type 被 Pydantic 拒绝。"""
        with pytest.raises(ValidationError):
            ConversationMessageCreate(
                task_id="tsk_test1234",
                message_type="chat",  # 不在枚举中
                body="随便聊聊。",
            )

    def test_empty_body_rejected(self):
        """空 body 被拒绝。"""
        with pytest.raises(ValidationError):
            ConversationMessageCreate(
                task_id="tsk_test1234",
                message_type="clarification",
                body="",  # min_length=1
            )


# ═════════════════════════════════════════════════════════════════════════
# Schema: ConversationMessageUpdate
# ═════════════════════════════════════════════════════════════════════════


class TestConversationMessageUpdate:
    """更新 A2A 消息 schema 校验。"""

    def test_resolve_only(self):
        """仅标记 resolved。"""
        update = ConversationMessageUpdate(is_resolved=True)
        assert update.is_resolved is True
        assert update.body is None

    def test_edit_body_only(self):
        """仅编辑正文。"""
        update = ConversationMessageUpdate(body="更新后的澄清内容。")
        assert update.body == "更新后的澄清内容。"
        assert update.is_resolved is None

    def test_empty_update_allowed(self):
        """空更新合法 — 所有字段可选。"""
        update = ConversationMessageUpdate()
        assert update.body is None
        assert update.is_resolved is None


# ═════════════════════════════════════════════════════════════════════════
# Schema: ConversationMessageResponse
# ═════════════════════════════════════════════════════════════════════════


class TestConversationMessageResponse:
    """A2A 消息响应体 schema 校验。"""

    def test_from_attributes_config(self):
        """响应体启用 from_attributes 模式。"""
        assert ConversationMessageResponse.model_config["from_attributes"] is True

    def test_minimal_response(self):
        """最小响应 — 只有必填字段。"""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        resp = ConversationMessageResponse(
            id="twc_msg1234",
            task_id="tsk_test1234",
            sender_worker_id="ag_sender001",
            message_type="clarification",
            body="这是澄清消息。",
            is_resolved=False,
            is_disabled=False,
            create_user_id="ag_sender001",
            version_no=1,
            created_at=now,
            updated_at=now,
        )
        assert resp.id == "twc_msg1234"
        assert resp.is_resolved is False
        assert resp.workflow_id is None
        assert resp.authorization_request_id is None


# ═════════════════════════════════════════════════════════════════════════
# Model: TaskWorkerConversation
# ═════════════════════════════════════════════════════════════════════════


class TestTaskWorkerConversationModel:
    """ORM 模型基础属性测试。"""

    def test_defaults(self):
        """模型构造时 Python 侧默认值。

        SQLAlchemy mapped_column 的 ``default`` 仅在 DB INSERT 时生效，
        Python 侧构造时可为 None（与 ``server_default`` 行为一致）。
        """
        msg = TaskWorkerConversation(
            id="twc_test001",
            task_id="tsk_test1234",
            sender_worker_id="ag_sender001",
            message_type="clarification",
            body="默认值测试。",
        )
        # DB-insert 侧默认值 — Python 构造时不生效
        assert msg.resolved_at is None
        assert msg.resolved_by_worker_id is None
        # 显式传入或未传的可空字段
        assert msg.workflow_id is None
        assert msg.in_reply_to_id is None
        assert msg.authorization_request_id is None

    def test_table_name(self):
        """表名正确。"""
        assert TaskWorkerConversation.__tablename__ == "task_worker_conversation"

    def test_message_type_values(self):
        """四种 message_type 均可构造。"""
        for mt in ("clarification", "blocking", "review_request", "handoff"):
            msg = TaskWorkerConversation(
                id=f"twc_test_{mt}",
                task_id="tsk_test1234",
                sender_worker_id="ag_sender001",
                message_type=mt,
                body=f"测试 {mt} 类型。",
            )
            assert msg.message_type == mt
