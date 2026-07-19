"""CircuitBreaker API 端点 — 熔断器状态查询 + 手动复位。

P10-B37: 议题 ⑥ API 层首次落地。

端点:
- GET    /circuit-breakers          分页列表
- GET    /circuit-breakers/{id}     单条详情
- POST   /circuit-breakers/{id}/reset  手动复位
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, require_role
from src.exceptions import NotFoundError
from src.models.circuit_breaker import CircuitBreaker
from src.schemas.common import CursorPage
from src.schemas.protection import CircuitBreakerResponse
from src.services.circuit_breaker_service import reset_breaker

router = APIRouter()


# ── 内部辅助 ──────────────────────────────────────────────────────────


def _to_response(record: CircuitBreaker) -> CircuitBreakerResponse:
    """ORM → Pydantic。CircuitBreaker 无 JSON 字段，直接映射。"""
    return CircuitBreakerResponse.model_validate(record)


# ═══════════════════════════════════════════════════════════════════════
# GET /circuit-breakers
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/circuit-breakers",
    response_model=CursorPage[CircuitBreakerResponse],
)
async def list_circuit_breakers(
    target_type: str | None = Query(
        None, pattern=r"^(worker|project)$",
    ),
    state: str | None = Query(
        None, pattern=r"^(closed|open|half_open)$",
    ),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """分页查询熔断器状态，按创建时间降序。

    支持按 target_type、state 筛选。
    仅 admin 角色可访问。
    """
    conditions: list = []
    if target_type:
        conditions.append(CircuitBreaker.target_type == target_type)
    if state:
        conditions.append(CircuitBreaker.state == state)
    if cursor:
        conditions.append(CircuitBreaker.id < cursor)

    stmt = (
        select(CircuitBreaker)
        .where(*conditions)
        .order_by(CircuitBreaker.created_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = select(func.count(CircuitBreaker.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar()

    return CursorPage(
        items=[_to_response(r) for r in items],
        next_cursor=next_cursor,
        total=total,
    )


# ═══════════════════════════════════════════════════════════════════════
# GET /circuit-breakers/{breaker_id}
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/circuit-breakers/{breaker_id}",
    response_model=CircuitBreakerResponse,
)
async def get_circuit_breaker(
    breaker_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """获取单个熔断器详情。"""
    result = await db.execute(
        select(CircuitBreaker).where(CircuitBreaker.id == breaker_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("CircuitBreaker", breaker_id)

    return _to_response(record)


# ═══════════════════════════════════════════════════════════════════════
# POST /circuit-breakers/{breaker_id}/reset
# ═══════════════════════════════════════════════════════════════════════


@router.post(
    "/circuit-breakers/{breaker_id}/reset",
    response_model=CircuitBreakerResponse,
)
async def reset_circuit_breaker(
    breaker_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """手动复位熔断器 — 强制恢复到 CLOSED 状态并清零计数器。

    无论当前状态如何（OPEN/HALF_OPEN/CLOSED），强制复位为 CLOSED。
    记录 CIRCUIT_BREAKER_CLOSED 事件（含 override 标记）。
    """
    # 先查出 target_type / target_id
    result = await db.execute(
        select(CircuitBreaker).where(CircuitBreaker.id == breaker_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("CircuitBreaker", breaker_id)

    updated = await reset_breaker(
        db,
        target_type=record.target_type,
        target_id=record.target_id,
    )
    await db.commit()

    return _to_response(updated)
