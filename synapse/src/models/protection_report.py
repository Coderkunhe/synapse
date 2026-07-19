"""ProtectionReport 模型 — 保护报告。

议题 ⑥（保护报告+熔断+决策审计）数据基础层。

三种检测模式：
- cross_project_access: 跨 Project 访问检测
- sensitive_overlap: 敏感 Worker 重叠检测
- capability_drift: Worker 能力漂移检测

报告可手动触发或定时调度，异步生成后填充 result_json。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import AuditMixin, Base


class ProtectionReport(Base, AuditMixin):
    __tablename__ = "protection_reports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    # ── 归属 ──
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True,
        comment="所属 Project",
    )

    # ── 报告类型 ──
    report_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
        comment="cross_project_access | sensitive_overlap | capability_drift",
    )

    # ── 状态机 ──
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
        comment="pending | running | completed | failed",
    )

    # ── 触发方式 ──
    triggered_by: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual",
        comment="manual | scheduled",
    )

    # ── 参数 ──
    parameters_json: Mapped[str | None] = mapped_column(
        String(4000), nullable=True,
        comment="报告参数 (JSON) — 检测阈值、范围等配置",
    )

    # ── 结果 ──
    result_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="报告结果 (JSON) — completed 时填充，含发现项、风险评分等",
    )

    # ── 时间戳 ──
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="开始执行时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
        comment="完成时间",
    )

    # ── 关联 ──
    project: Mapped["Project"] = relationship("Project")
