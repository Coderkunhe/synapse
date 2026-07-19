"""Team 模型 — 顶层租户边界。"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class Team(Base, AuditMixin):
    __tablename__ = "team"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # 关联关系
    members: Mapped[list["Member"]] = relationship("Member", back_populates="team")
    team_members: Mapped[list["TeamMember"]] = relationship("TeamMember", back_populates="team")
    workers: Mapped[list["Worker"]] = relationship("Worker", back_populates="team")
    projects: Mapped[list["Project"]] = relationship("Project", back_populates="team")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="team")
    skills: Mapped[list["Skill"]] = relationship("Skill", back_populates="team")
