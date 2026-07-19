"""ScanResult 模型 — 不可变的合规扫描记录。"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import AuditMixin, Base


class ScanResult(Base, AuditMixin):
    """某时刻的合规扫描快照。

    不可变 — 无 update 或 delete 端点。每次扫描创建一条新记录，
    形成审计追踪链。

    ``rules_checked`` 以 JSON 文本 blob 存储完整裁决数组，
    使扫描结果自包含（无需 join 单独的规则-结果表）。
    """

    __tablename__ = "scan_result"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    team_id: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    rules_checked: Mapped[str] = mapped_column(Text, nullable=False)
    summary_pass: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_fail: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_warn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
