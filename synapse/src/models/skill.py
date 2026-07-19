"""Skill 模型 — Worker 工人的统一入职包 + 协议定义。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants import SkillStatus
from src.models.base import AuditMixin, Base


class Skill(Base, AuditMixin):
    """Skill 定义既是入职文档也是协议契约。

    设计 (mvp-boundary.md §5.1)：一份 Skill 定义 = Worker 知道如何工作
    (template_md) + 平台知道如何验证 (protocol_spec)。不在两个来源间重复。

    ``protocol_spec`` 和 ``scan_rule_ids`` 以 JSON 文本 blob 存储，
    使 Skill 记录自包含 — 与 ScanResult 同模式。
    """

    __tablename__ = "skill"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("team.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0.0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SkillStatus.ACTIVE, index=True
    )
    template_md: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_spec: Mapped[str | None] = mapped_column(
        String(4000), nullable=True
    )
    scan_rule_ids: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )
    metadata_: Mapped[str | None] = mapped_column(
        "metadata", String(4000), nullable=True
    )

    # 关联关系
    team: Mapped["Team"] = relationship("Team", back_populates="skills")
