"""AnalysisRecord schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.constants import ActorType
from src.schemas.common import AuditFields


class AnalysisCreate(BaseModel):
    """创建 AnalysisRecord 的请求体。

    actor_type 和 actor_id 从已认证角色派生，不接受来自请求体的传入。
    """

    analysis_type: str = Field(
        ...,
        pattern=r"^(requirement|discussion|design)$",
    )
    title: str = Field(..., max_length=500)
    content: str = Field(..., min_length=1)
    source_batch_id: str | None = Field(None, max_length=40)
    metadata_: dict | None = Field(None, alias="metadata")


class AnalysisResponse(AuditFields):
    """AnalysisRecord 读取操作的响应体。"""

    id: str
    project_id: str
    actor_type: ActorType
    actor_id: str
    analysis_type: str
    title: str
    content: str
    source_batch_id: str | None = None
    metadata_: dict | None = Field(None, alias="metadata")

    model_config = {"from_attributes": True, "populate_by_name": True}
