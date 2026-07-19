"""P10-B20: AuthorizationRequest 模型 + Schema 基础测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.models.authorization_request import AuthorizationRequest
from src.schemas.authorization_request import (
    AuthorizationRequestCreate,
    AuthorizationRequestHeartbeat,
    AuthorizationRequestRespond,
    AuthorizationRequestResponse,
)


# ═════════════════════════════════════════════════════════════════════════
# Schema: AuthorizationRequestCreate
# ═════════════════════════════════════════════════════════════════════════


class TestAuthorizationRequestCreate:
    """创建授权请求 schema 校验。"""

    def test_api_auth_minimal(self):
        """api_auth 类型最小字段：request_type + project_id + worker_id + operation。"""
        req = AuthorizationRequestCreate(
            project_id="proj-1",
            worker_id="worker-1",
            request_type="api_auth",
            operation="task.assign",
        )
        assert req.request_type == "api_auth"
        assert req.operation == "task.assign"
        assert req.ttl_seconds == 3600  # default

    def test_api_auth_full(self):
        """api_auth 类型完整字段含 target_resource。"""
        req = AuthorizationRequestCreate(
            project_id="proj-1",
            worker_id="worker-1",
            request_type="api_auth",
            operation="batch.cancel",
            target_resource_type="batch",
            target_resource_id="batch-42",
            ttl_seconds=7200,
        )
        assert req.target_resource_type == "batch"
        assert req.target_resource_id == "batch-42"
        assert req.ttl_seconds == 7200

    def test_interactive_prompt_confirm(self):
        """interactive_prompt confirm 类型。"""
        req = AuthorizationRequestCreate(
            project_id="proj-1",
            worker_id="worker-1",
            request_type="interactive_prompt",
            prompt_type="confirm",
            prompt_message="确认部署到生产环境？",
        )
        assert req.request_type == "interactive_prompt"
        assert req.prompt_type == "confirm"
        assert req.prompt_message == "确认部署到生产环境？"

    def test_interactive_prompt_choice(self):
        """interactive_prompt choice 类型含选项列表。"""
        req = AuthorizationRequestCreate(
            project_id="proj-1",
            worker_id="worker-1",
            request_type="interactive_prompt",
            prompt_type="choice",
            prompt_message="选择部署环境",
            prompt_choices=["staging", "production", "canary"],
        )
        assert req.prompt_type == "choice"
        assert len(req.prompt_choices) == 3

    def test_interactive_prompt_input(self):
        """interactive_prompt input 类型。"""
        req = AuthorizationRequestCreate(
            project_id="proj-1",
            worker_id="worker-1",
            request_type="interactive_prompt",
            prompt_type="input",
            prompt_message="请输入版本号",
        )
        assert req.prompt_type == "input"

    def test_invalid_request_type_rejected(self):
        """非法 request_type 被 pydantic 校验拒绝。"""
        with pytest.raises(ValidationError):
            AuthorizationRequestCreate(
                project_id="proj-1",
                worker_id="worker-1",
                request_type="invalid_type",
            )

    def test_invalid_prompt_type_rejected(self):
        """非法 prompt_type 被拒绝。"""
        with pytest.raises(ValidationError):
            AuthorizationRequestCreate(
                project_id="proj-1",
                worker_id="worker-1",
                request_type="interactive_prompt",
                prompt_type="invalid_prompt",
                prompt_message="test",
            )

    def test_ttl_out_of_range_rejected(self):
        """ttl_seconds 超出 [60, 86400] 被拒绝。"""
        with pytest.raises(ValidationError):
            AuthorizationRequestCreate(
                project_id="proj-1",
                worker_id="worker-1",
                request_type="api_auth",
                operation="task.assign",
                ttl_seconds=30,  # below min 60
            )

        with pytest.raises(ValidationError):
            AuthorizationRequestCreate(
                project_id="proj-1",
                worker_id="worker-1",
                request_type="api_auth",
                operation="task.assign",
                ttl_seconds=100000,  # above max 86400
            )


# ═════════════════════════════════════════════════════════════════════════
# Schema: AuthorizationRequestRespond
# ═════════════════════════════════════════════════════════════════════════


class TestAuthorizationRequestRespond:
    """审批响应 schema 校验。"""

    def test_approve_minimal(self):
        """approve 状态最小字段。"""
        resp = AuthorizationRequestRespond(status="approved")
        assert resp.status == "approved"
        assert resp.response_note is None

    def test_deny_with_note(self):
        """deny 状态含拒绝理由。"""
        resp = AuthorizationRequestRespond(
            status="denied",
            response_note="当前不允许生产部署",
        )
        assert resp.status == "denied"
        assert resp.response_note == "当前不允许生产部署"

    def test_choice_response_with_data(self):
        """choice 类型审批含选择结果。"""
        resp = AuthorizationRequestRespond(
            status="approved",
            response_data="staging",
        )
        assert resp.status == "approved"
        assert resp.response_data == "staging"

    def test_invalid_status_rejected(self):
        """非法 status 被拒绝。"""
        with pytest.raises(ValidationError):
            AuthorizationRequestRespond(status="pending")  # only approved/denied allowed


# ═════════════════════════════════════════════════════════════════════════
# Schema: AuthorizationRequestHeartbeat
# ═════════════════════════════════════════════════════════════════════════


class TestAuthorizationRequestHeartbeat:
    """心跳续期 schema。"""

    def test_heartbeat_empty_body(self):
        """心跳请求无必填字段。"""
        hb = AuthorizationRequestHeartbeat()
        assert hb is not None


# ═════════════════════════════════════════════════════════════════════════
# Schema: AuthorizationRequestResponse
# ═════════════════════════════════════════════════════════════════════════


class TestAuthorizationRequestResponse:
    """响应 schema 构造。"""

    def test_response_from_api_auth(self):
        """从 api_auth 类型的完整字段构造响应。"""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=1)
        resp = AuthorizationRequestResponse(
            id="ar-001",
            project_id="proj-1",
            worker_id="worker-1",
            request_type="api_auth",
            operation="task.assign",
            target_resource_type="task",
            target_resource_id="task-42",
            status="pending",
            expires_at=expires,
            last_heartbeat_at=now,
            is_disabled=False,
            create_user_id="worker-1",
            last_update_user_id=None,
            remark=None,
            version_no=1,
            created_at=now,
            updated_at=now,
        )
        assert resp.id == "ar-001"
        assert resp.request_type == "api_auth"
        assert resp.status == "pending"
        assert resp.operation == "task.assign"
        # interactive_prompt 字段应为 None
        assert resp.prompt_type is None
        assert resp.prompt_message is None

    def test_response_after_approval(self):
        """审批后的响应含 response 字段。"""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=1)
        resp = AuthorizationRequestResponse(
            id="ar-002",
            project_id="proj-1",
            worker_id="worker-1",
            request_type="interactive_prompt",
            prompt_type="confirm",
            prompt_message="确认部署？",
            status="approved",
            responded_by_worker_id="human-1",
            responded_at=now,
            response_note="同意",
            expires_at=expires,
            last_heartbeat_at=now,
            is_disabled=False,
            create_user_id="worker-1",
            version_no=1,
            created_at=now,
            updated_at=now,
        )
        assert resp.status == "approved"
        assert resp.responded_by_worker_id == "human-1"
        assert resp.response_note == "同意"


# ═════════════════════════════════════════════════════════════════════════
# Model: AuthorizationRequest ORM
# ═════════════════════════════════════════════════════════════════════════


class TestAuthorizationRequestModel:
    """SQLAlchemy 模型构造和默认值。"""

    def test_model_defaults(self):
        """模型构造：显式设置字段 + AuditMixin 默认值（server_default 在 Python 侧不生效）。"""
        now = datetime.now(timezone.utc)
        ar = AuthorizationRequest(
            id="ar-001",
            project_id="proj-1",
            worker_id="worker-1",
            request_type="api_auth",
            operation="task.assign",
            status="pending",
            expires_at=now + timedelta(hours=1),
        )
        assert ar.id == "ar-001"
        assert ar.status == "pending"
        assert ar.request_type == "api_auth"
        # server_default 在 DB insert 时才生效，Python 构造时为 None
        # is_disabled / version_no / create_user_id 由 DB server_default 提供
        # 未设置的 api_auth 字段为 None
        assert ar.target_resource_type is None

    def test_model_prompt_fields(self):
        """interactive_prompt 模型 prompt 字段存储。"""
        now = datetime.now(timezone.utc)
        ar = AuthorizationRequest(
            id="ar-002",
            project_id="proj-1",
            worker_id="worker-1",
            request_type="interactive_prompt",
            prompt_type="choice",
            prompt_message="选择环境",
            prompt_choices_json='["staging","production"]',
            expires_at=now + timedelta(hours=1),
        )
        assert ar.prompt_type == "choice"
        assert ar.prompt_choices_json == '["staging","production"]'
        # api_auth 字段为 None
        assert ar.operation is None

    def test_model_responded_fields(self):
        """审批后模型 stored response 字段。"""
        now = datetime.now(timezone.utc)
        ar = AuthorizationRequest(
            id="ar-003",
            project_id="proj-1",
            worker_id="worker-1",
            request_type="api_auth",
            operation="task.assign",
            status="approved",
            responded_by_worker_id="human-1",
            responded_at=now,
            response_note="ok",
            expires_at=now + timedelta(hours=1),
        )
        assert ar.status == "approved"
        assert ar.responded_by_worker_id == "human-1"
        assert ar.response_note == "ok"
