"""Worker 模型 — 人和 AI 的统一执行者身份。

ADR-004 四实体架构：Worker 是执行层的统一实体，同一张表容纳人类和 AI。
``actor_type`` 列区分 human / agent。

人类 Worker 由系统自动创建（User 注册时），不可手动注册、不可删除。
Agent Worker 由人类 Worker 注册，可暂停/删除。

两个正交的状态维度：
- ``status`` (WorkerStatus)：生命周期 — pending → active → inactive
- ``runtime_status`` (WorkerRuntimeStatus)：运行时 — idle → busy → error

只有 ``status=active`` 的 worker 参与运行时调度池。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants import WorkerActorType, WorkerRuntimeStatus, WorkerStatus
from src.models.base import AuditMixin, Base


class Worker(Base, AuditMixin):
    __tablename__ = "worker"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── P10-B2: ADR-004 四实体架构扩展 ──────────────────────────────
    actor_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default=WorkerActorType.AGENT, index=True,
        comment="human | agent — 同一张表，人和 AI 统一建模",
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id"), nullable=True, index=True,
        comment="人类 User 的 FK — agent 行为 NULL",
    )
    # ────────────────────────────────────────────────────────────────

    team_id: Mapped[str] = mapped_column(ForeignKey("team.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="claude")
    provider_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    registered_by: Mapped[str | None] = mapped_column(
        ForeignKey("worker.id"), nullable=True,
        comment="注册此 Agent 的 Worker ID — 通常指向人类 Worker；系统自建为 NULL",
    )
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(12), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=WorkerStatus.PENDING, index=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[str | None] = mapped_column("metadata", String(4000), nullable=True)

    # ── 运行时字段 (P8-B2) ────────────────────────────────────────────
    # 与生命周期状态独立；仅在 status=active 时有意义。
    runtime_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=WorkerRuntimeStatus.IDLE, index=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_task_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    capability_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    """从 Capability 表中提取的反规范化能力摘要，在 handshake 期间生成。
    格式：``{"names": ["code-review", "plan"], "count": 2}``。
    """

    # ── Batch 原子性 (P9-B57) ───────────────────────────────────────────
    batch_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3,
        comment="Worker 适合处理的最大 Batch 任务数，默认 3（对齐人脑并行追踪上限）"
    )

    # 关联关系
    user: Mapped["User | None"] = relationship("User", foreign_keys=[user_id])
    team: Mapped["Team"] = relationship("Team", back_populates="workers")
    registered_by_worker: Mapped["Worker | None"] = relationship(
        "Worker", remote_side=[id], foreign_keys=[registered_by],
    )
    capabilities: Mapped[list["Capability"]] = relationship(
        "Capability", back_populates="worker", cascade="all, delete-orphan"
    )
