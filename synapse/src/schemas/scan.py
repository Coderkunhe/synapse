"""ComplianceScan schema — 扫描执行的请求/响应。

POST /v1/scan/{target_type}/{target_id} 仅接受路径参数（无请求体），
因此不需要请求体 schema。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.constants import ActorType
from src.schemas.common import AuditFields


class RuleVerdict(BaseModel):
    """单条规则检查结果。"""

    rule_id: str
    status: str = Field(..., pattern=r"^(pass|fail|warn)$")
    detail: str


class ScanSummary(BaseModel):
    """规则判定状态的聚合计数。"""

    pass_: int = Field(0, alias="pass")
    fail: int = Field(0)
    warn: int = Field(0)


class ScanResponse(AuditFields):
    """已完成合规扫描的响应体。"""

    id: str
    target_type: str
    target_id: str
    actor_type: ActorType
    actor_id: str
    rules_checked: list[RuleVerdict]
    summary: ScanSummary

    model_config = {"from_attributes": True, "populate_by_name": True}

