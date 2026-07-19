"""Workflow + WorkflowRole 模型 — per-Workflow 角色分配。

P10-B24: 议题 4 per-Workflow 角色 — 数据基础层。

Workflow = Project 内的协调上下文（命名团队），包含角色分配。
WorkflowRole = Worker 在某个 Workflow 中的临时职能。

同一个 Worker 在不同 Workflow 中可承担不同角色（架构 §4.5.2）：
- Worker A 在 Workflow X 中是 Builder
- Worker A 在 Workflow Y 中是 Orchestrator

P10 实现 O+B 双角色；Steward 模型支持但功能暂不暴露（D-P10-004）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class Workflow(Base, AuditMixin):
    """Project 内的协调上下文 — 命名团队 + 角色分配。

    对标架构 §4.5.3 "2-pizza 原则"：
    一个 Workflow 基本单元 = 1 Orchestrator + 1-3 Builder + 可选 Steward。
    """

    __tablename__ = "workflow"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True,
        comment="所属 Project",
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="Workflow 名称 — 如 'P10 架构升级', '前端 UI'",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Workflow 目标描述",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True,
        comment="active | completed | cancelled",
    )

    # 关联关系
    project: Mapped["Project"] = relationship("Project", back_populates="workflows")
    workflow_roles: Mapped[list["WorkflowRole"]] = relationship(
        "WorkflowRole", back_populates="workflow", cascade="all, delete-orphan",
    )
    batches: Mapped[list["Batch"]] = relationship(
        "Batch", back_populates="workflow",
    )


class WorkflowRole(Base, AuditMixin):
    """Worker 在 Workflow 中的临时职能。

    独立于 ProjectActorRole — 后者负责 Project 级管理权限（admin/lead/member），
    本表负责 Workflow 内协作职能（orchestrator/builder）。
    同一 Worker 在不同 Workflow 中可承担不同角色。
    """

    __tablename__ = "workflow_role"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "worker_id",
            name="uq_workflow_role_workflow_worker",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow.id"), nullable=False, index=True,
        comment="所属 Workflow",
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="Workflow 中的 Worker（人或 AI）",
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="Workflow 内临时职能 — orchestrator | builder (P10) | steward (预留)",
    )

    # 关联关系
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="workflow_roles")
    worker: Mapped["Worker"] = relationship("Worker")
