"""Capability schema — 能力定义的 API 序列化层。

P11-B46: Capability MVP — 从 capabilities.yaml 读取并返回能力列表。
"""

from __future__ import annotations

from pydantic import BaseModel


class CapabilityResponse(BaseModel):
    """单个能力的 API 响应体。"""

    id: str
    name: str
    description: str
    category: str
    risk: str
    approval_policy: str
    command: str
    cwd: str | None = None
    timeout: int = 60
    evidence_required: bool = False
    dangerous_patterns: list[str] | None = None  # B51: shell_dangerous 黑名单
    protected_paths: list[str] | None = None     # B51: shell_dangerous 保护路径

    model_config = {"from_attributes": False}
