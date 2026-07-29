"""Task 模型 — 核心工作单元，支持多态 owner（Member 或 Worker）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants import TaskStatus
from src.models.base import AuditMixin, Base
from src.task_state_machine import ALLOWED_TRANSITIONS as _STATE_MACHINE_TRANSITIONS


class Task(Base, AuditMixin):
    __tablename__ = "task"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_type: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskStatus.BACKLOG, index=True)
    priority: Mapped[str] = mapped_column(String(5), nullable=False, default="p2")
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("task.id"), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batch.id"), nullable=True, index=True)
    estimated_effort: Mapped[str | None] = mapped_column(String(5), nullable=True)
    tags: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    required_capabilities: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    metadata_: Mapped[str | None] = mapped_column("metadata", String(4000), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── PAUSED 状态追踪 (P8-B1) ───────────────────────────────────────
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paused_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── 所有权生命周期 (P8-B1) ────────────────────────────────────────
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── 重做追踪 (P8-B5) ──────────────────────────────────────────────
    redo_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # ── 失败追踪 (P8-B7) ──────────────────────────────────────────────
    failure_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── 任务依赖 (P9-B6) ──────────────────────────────────────────────
    depends_on: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # version_no 继承自 AuditMixin（乐观锁）。
    # 向后兼容别名 — 服务层更新后在 B50 移除。
    @property
    def version(self) -> int:
        """version_no 的向后兼容别名。"""
        return self.version_no

    @version.setter
    def version(self, value: int) -> None:
        self.version_no = value

    # 关联关系
    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    parent_task: Mapped["Task | None"] = relationship(
        "Task", remote_side=[id], back_populates="subtasks"
    )
    subtasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="parent_task"
    )
    batch: Mapped["Batch | None"] = relationship("Batch", back_populates="tasks")
    verifications: Mapped[list["Verification"]] = relationship(
        "Verification", back_populates="task", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="task",
        primaryjoin="foreign(Event.target_id) == Task.id",
        viewonly=True,
    )

    # 多态 owner：只读便捷关联
    # 无数据库级 FK — owner 根据 owner_type 可以是 Member 或 Worker
    member_owner: Mapped["Member | None"] = relationship(
        "Member",
        primaryjoin="and_(foreign(Task.owner_type) == 'member', "
                    "foreign(Task.owner_id) == Member.id)",
        viewonly=True,
        uselist=False,
    )
    worker_owner: Mapped["Worker | None"] = relationship(
        "Worker",
        primaryjoin="and_(foreign(Task.owner_type) == 'worker', "
                    "foreign(Task.owner_id) == Worker.id)",
        viewonly=True,
        uselist=False,
    )

    # 有效 task 状态 — 委托给 TaskStatus 枚举
    VALID_STATUSES = frozenset(TaskStatus)

    # 有效状态转换 (from → {to}) — 委托给 task_state_machine。
    # 此属性保留用于向后兼容；服务代码应优先直接调用
    # ``task_state_machine.validate_transition()``。
    ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
        k: frozenset(v) for k, v in _STATE_MACHINE_TRANSITIONS.items()
    }
