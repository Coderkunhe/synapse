"""ProjectActorRole 模型 — Project → Worker 权限映射。

ADR-004 四实体架构：``project_actor_roles`` 是 Project 到 Worker 的硬权限映射，
替代旧 ``member.role`` 的全局权限。Project 才是权限的真正主体，Team 只是可选归属。

一个 Worker 在一个 Project 里只有一条角色记录（唯一约束）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class ProjectActorRole(Base, AuditMixin):
    __tablename__ = "project_actor_roles"
    __table_args__ = (
        UniqueConstraint("project_id", "worker_id", name="uq_project_actor_roles_project_worker"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True,
        comment="所属 Project",
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="Project 中的 Worker（人或 AI）",
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member",
        comment="Project 内角色标签 — orchestrator / builder / steward 等",
    )

    # 关联关系
    project: Mapped["Project"] = relationship("Project", back_populates="project_actor_roles")
    worker: Mapped["Worker"] = relationship("Worker")
