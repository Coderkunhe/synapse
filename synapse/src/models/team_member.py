"""TeamMember 模型 — Team → Worker 可选多对多映射。

ADR-004 四实体架构：``team_members`` 是 Team 到 Worker 的归属关系，
替代旧 ``member`` 表的 Team 绑定功能。旧表混合了身份（display_name/email/OAuth）
和归属（team_id/role），ADR-004 将它们分离——身份进 ``users``，归属进 ``team_members``。

一个 Worker 在一个 Team 里只有一条 membership（唯一约束）。
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class TeamMember(Base, AuditMixin):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "worker_id", name="uq_team_members_team_worker"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("team.id"), nullable=False, index=True,
        comment="所属 Team",
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("worker.id"), nullable=False, index=True,
        comment="Team 中的 Worker（人或 AI）",
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member",
        comment="Team 内角色标签 — lead / member 等",
    )
    notes: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="备注（如加入原因、特殊说明）",
    )

    # 关联关系
    team: Mapped["Team"] = relationship("Team", back_populates="team_members")
    worker: Mapped["Worker"] = relationship("Worker")
