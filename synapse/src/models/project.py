"""Project 模型 — 软件项目的协调空间。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants import ProjectStatus
from src.models.base import AuditMixin, Base


class Project(Base, AuditMixin):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("team_id", "slug", name="uq_project_team_slug"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("team.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=ProjectStatus.ACTIVE, index=True)
    default_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    git_repo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    api_docs_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    frontend_test_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True,
        comment="Per-project webhook URL for event notifications (P10-B34)",
    )
    project_key_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
        comment="SHA-256 hash of project access key — unguessable credential for Worker discovery (P11-B8)",
    )
    use_phase_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="Phase/Sprint 二级编号模式开关 (P10-B40)",
    )
    current_phase: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="当前 Phase 名称/目标声明 (P10-B40)",
    )
    organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    metadata_: Mapped[str | None] = mapped_column("metadata", String(4000), nullable=True)
    is_protected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0"),
        comment="防误删保护标记 — 受保护项目不可归档/删除",
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="归档时间 — 硬删除时用于计算 7 天冷静期",
    )

    # 关联关系
    team: Mapped["Team"] = relationship("Team", back_populates="projects")
    project_actor_roles: Mapped[list["ProjectActorRole"]] = relationship(
        "ProjectActorRole", back_populates="project",
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="project")
    batches: Mapped[list["Batch"]] = relationship("Batch", back_populates="project")
    workflows: Mapped[list["Workflow"]] = relationship(
        "Workflow", back_populates="project",
    )
