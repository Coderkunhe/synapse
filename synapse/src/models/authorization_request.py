"""AuthorizationRequest 模型 — 异步授权请求。

议题 3（异步授权管道）数据基础层。三种类型单表设计：

- **api_auth**: Worker 操作被 403 → 系统自动创建 → 人类审批 → 系统代执行（方案 B）
- **interactive_prompt**: 系统需人类输入 → 创建 confirm/choice/input 提示 → 人类响应
- **capability_exec**: Worker 主动请求执行能力 → 人类审批 → Worker 执行 → Worker 上报（P11-B46）

TTL + 心跳确保存活保证。过期/Worker 离线 → 自动 expired/cancelled。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base, _utcnow


class AuthorizationRequest(Base, AuditMixin):
    __tablename__ = "authorization_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── 归属 ──
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True,
        comment="所属 Project",
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="发起请求的 Worker",
    )

    # ── 类型鉴别 ──
    request_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="api_auth | interactive_prompt",
    )

    # ── api_auth 字段组（request_type=api_auth 时使用）──
    operation: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="操作名，如 task.assign / batch.cancel / project.update",
    )
    target_resource_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="目标资源类型 — task / batch / project / verification",
    )
    target_resource_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
        comment="目标资源 ID",
    )

    # ── interactive_prompt 字段组（request_type=interactive_prompt 时使用）──
    prompt_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="confirm | choice | input",
    )
    prompt_message: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="提示消息（人类可读）",
    )
    prompt_choices_json: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="JSON 数组 — choice 类型的选项列表",
    )

    # ── 状态机 ──
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
        comment="pending | approved | denied | expired | cancelled",
    )

    # ── 审批/响应 ──
    responded_by_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("worker.id"), nullable=True,
        comment="响应此请求的人类 Worker ID",
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="响应时间",
    )
    response_note: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="审批备注/拒绝理由",
    )
    response_data_json: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="JSON — choice 选择结果 / input 文本输入 / confirm 时为 null",
    )

    # ── capability_exec 字段组（request_type=capability_exec 时使用 · P11-B46）──
    capability_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="能力 ID — 如 git_push_main",
    )
    outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="执行结果 — success | failure",
    )
    exit_code: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="进程退出码",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="执行耗时（毫秒）",
    )

    # ── 存活保证 ──
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        comment="过期时间 — 默认创建后 1 小时，Worker 可通过心跳续期",
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
        comment="最后一次心跳时间",
    )

    # ── 关联关系 ──
    project: Mapped["Project"] = relationship("Project")
    worker: Mapped["Worker"] = relationship("Worker", foreign_keys=[worker_id])
    responded_by: Mapped["Worker | None"] = relationship(
        "Worker", foreign_keys=[responded_by_worker_id],
    )
