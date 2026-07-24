"""Capability API 端点 — 能力定义查询。

P11-B46: Capability MVP — GET /workers/{id}/capabilities 端点。
从 config/capabilities.yaml 读取能力定义并返回。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends

from src.dependencies import ActorInfo, get_current_actor
from src.schemas.capabilities import CapabilityResponse

router = APIRouter()

# 能力定义文件路径（相对于 synapse/ 目录）
_CAPABILITIES_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "capabilities.yaml"


def _load_capabilities() -> list[dict]:
    """从 YAML 文件加载能力定义。"""
    if not _CAPABILITIES_PATH.exists():
        return []
    try:
        with open(_CAPABILITIES_PATH) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return []
    return data.get("capabilities", []) if data else []


@router.get(
    "/workers/{worker_id}/capabilities",
    response_model=list[CapabilityResponse],
)
async def get_worker_capabilities(
    worker_id: str,
    actor: ActorInfo = Depends(get_current_actor),
):
    """获取 Worker 可用的能力列表。

    当前 MVP 阶段返回全局能力定义（不按 Worker 过滤）。
    认证要求：任何已认证的 actor（Worker 或 Human）均可查询。
    """
    caps = _load_capabilities()
    return [CapabilityResponse(**c) for c in caps]
