"""议题 ⑥ API schema — ProtectionReport + CircuitBreaker + DecisionAudit。

P10-B37: 议题 ⑥ API 层首次落地。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


# ═════════════════════════════════════════════════════════════════════════
# ProtectionReport — 请求体
# ═════════════════════════════════════════════════════════════════════════


class ProtectionReportCreate(BaseModel):
    """创建保护报告 — 手动触发检测任务。"""

    report_type: str = Field(
        ...,
        pattern=r"^(cross_project_access|sensitive_overlap|capability_drift)$",
    )
    parameters: dict | None = None


# ═════════════════════════════════════════════════════════════════════════
# ProtectionReport — 响应体
# ═════════════════════════════════════════════════════════════════════════


class ProtectionReportResponse(AuditFields):
    """保护报告的完整响应体。

    parameters_json / result_json 在 _to_response 中手动转换为
    parameters / result dict。
    """

    id: str
    project_id: str
    report_type: str
    status: str
    triggered_by: str
    parameters: dict | None = None
    result: dict | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ═════════════════════════════════════════════════════════════════════════
# CircuitBreaker — 响应体（只读，无创建 Schema）
# ═════════════════════════════════════════════════════════════════════════


class CircuitBreakerResponse(AuditFields):
    """熔断器状态的响应体。

    熔断器由 Service 层自动创建/管理，API 仅提供查询 + 手动复位。
    """

    id: str
    target_type: str
    target_id: str
    state: str
    failure_count: int
    last_failure_at: datetime | None = None
    opened_at: datetime | None = None
    cooldown_until: datetime | None = None

    model_config = {"from_attributes": True}


# ═════════════════════════════════════════════════════════════════════════
# DecisionAudit — 响应体（只读不可变，无创建/更新 Schema）
# ═════════════════════════════════════════════════════════════════════════


class DecisionAuditResponse(BaseModel):
    """决策审计记录的响应体。

    不继承 AuditFields — DecisionAudit 是不可变追加日志（与 Event 对齐），
    没有 updated_at / is_disabled / version_no 字段。
    """

    id: str
    authorization_request_id: str | None = None
    decision_type: str
    actor_type: str
    actor_id: str
    project_id: str
    worker_id: str
    risk_level: str
    reason: str | None = None
    context: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
