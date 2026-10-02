"""TaskWorkerConversation 模型 — A2A 结构化协调消息。

P10-B28: 议题 5 A2A 协议 — 数据基础层。

A2A 通信 = 故障指示灯（D-P10-003）。Worker 之间交谈越多，
说明任务拆分/规范越差。不建 DM/私聊，只建结构化协调消息。

四种消息类型：
- clarification: 澄清问题
- blocking: 阻塞信号
- review_request: 请求审查
- handoff: 任务交接（触发 AuthorizationRequest 管道）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, _utcnow


class TaskWorkerConversation(Base, AuditMixin):
    """Task 上下文中 Worker 之间的结构化协调消息。

    每行是一条消息。通过 in_reply_to_id 支持简单线程回复。
    handoff 类型通过 authorization_request_id 链接到授权审计链。
    """

    __tablename__ = "task_worker_conversation"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── 归属 ──
    task_id: Mapped[str] = mapped_column(
        ForeignKey("task.id"), nullable=False, index=True,
        comment="对话归属的任务",
    )
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow.id"), nullable=True, index=True,
        comment="可选 Workflow 上下文 — 用于 @role:orchestrator 角色解析",
    )
    sender_worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="消息发送者（人或 AI，统一为 Worker）",
    )

    # ── 消息分类 ──
    message_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="clarification | blocking | review_request | handoff | proposal",
    )

    # ── 消息内容 ──
    body: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="消息正文 — 支持 @worker:name / @role:rolename 语法",
    )
    mentions_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON 数组 — 被 @ 的 worker_id 列表（发送时解析写入）",
    )

    # ── 线程 ──
    in_reply_to_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_worker_conversation.id"), nullable=True, index=True,
        comment="回复目标消息 ID — 线程支持（自引用）",
    )

    # ── handoff 专属 ──
    authorization_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("authorization_requests.id"), nullable=True,
        comment="handoff 类型时关联的授权请求 ID — 串起审计链",
    )

    # ── 提案状态 (P11-B117 PFL-113) ──
    proposal_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True,
        comment="提案状态 — pending | confirmed | rejected · O 提案→Human 确认的协议追踪",
    )

    # ── 解决状态 ──
    is_resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="消息是否已解决 — blocking/clarification 可标记 resolved",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="解决时间",
    )
    resolved_by_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("worker.id"), nullable=True,
        comment="标记解决的 Worker ID",
    )

    # ── 关联关系 ──
    task: Mapped["Task"] = relationship("Task")
    workflow: Mapped["Workflow | None"] = relationship("Workflow")
    sender: Mapped["Worker"] = relationship("Worker", foreign_keys=[sender_worker_id])
    in_reply_to: Mapped["TaskWorkerConversation | None"] = relationship(
        "TaskWorkerConversation", remote_side=[id],
    )
    authorization_request: Mapped["AuthorizationRequest | None"] = relationship(
        "AuthorizationRequest",
    )
    resolved_by: Mapped["Worker | None"] = relationship(
        "Worker", foreign_keys=[resolved_by_worker_id],
    )


class TaskWorkerConversationMention(Base):
    """消息 → 被 @ worker 的关联表（P17-B12 · 可索引 mention 查询）。

    ``mentions_json`` 存 name 供展示；本表存解析后的 worker_id 供查询——
    根因是「JSON blob 不可索引」，关联表才真正可查。
    """

    __tablename__ = "task_worker_conversation_mention"
    __table_args__ = (
        UniqueConstraint("conversation_id", "worker_id",
                         name="uq_mention_conv_worker"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("task_worker_conversation.id"), nullable=False, index=True,
        comment="被 @ 的消息 ID",
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="被 @ 的 worker ID（resolve_mentions 解析结果落库）",
    )
