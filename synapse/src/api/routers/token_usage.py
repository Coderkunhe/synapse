"""TokenUsage API routes — 记录 + 查询 Worker token 消耗。

无独立 service 文件 — TokenLedger 逻辑简单，路由内联。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import ForbiddenError, NotFoundError
from src.models.worker import Worker
from src.models.token_usage import TokenUsage
from src.schemas.common import CursorPage
from src.schemas.token_usage import TokenUsageCreate, TokenUsageResponse
from src.utils.id_gen import generate_id

router = APIRouter()


def _usage_to_response(u: TokenUsage) -> dict:
    """将 ORM 对象转为 response 就绪的 dict。"""
    return {
        "id": u.id,
        "worker_id": u.worker_id,
        "task_id": u.task_id,
        "project_id": u.project_id,
        "provider": u.provider,
        "model": u.model,
        "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens,
        "total_tokens": u.prompt_tokens + u.completion_tokens,
        "cost": u.cost,
        "request_id": u.request_id,
        "recorded_at": u.recorded_at,
        "metadata_": u.metadata_,
        # AuditFields
        "is_disabled": u.is_disabled,
        "create_user_id": u.create_user_id,
        "last_update_user_id": u.last_update_user_id,
        "remark": u.remark,
        "version_no": u.version_no,
        "created_at": u.created_at,
        "updated_at": u.updated_at,
    }


@router.post(
    "/workers/{worker_id}/token-usage",
    response_model=TokenUsageResponse,
    status_code=201,
)
async def record_token_usage(
    worker_id: str,
    body: TokenUsageCreate,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """记录一条 Worker token 消耗。

    Worker 只能报自己的消耗；human member 可给任意 worker 上报。
    """
    # ── 验证 worker 存在 ──
    worker = await db.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError("worker", worker_id)

    # ── 权限：worker 只能报自己，human 不限 ──
    if actor.actor_type == ActorType.WORKER and actor.actor_id != worker_id:
        raise ForbiddenError(
            "FORBIDDEN_TOKEN_USAGE_SELF_ONLY",
            "Worker can only record its own token usage",
        )

    # ── 创建记录 ──
    now = datetime.now(timezone.utc)
    usage = TokenUsage(
        id=generate_id("token_usage"),
        worker_id=worker_id,
        task_id=body.task_id,
        project_id=body.project_id,
        provider=body.provider,
        model=body.model,
        prompt_tokens=body.prompt_tokens,
        completion_tokens=body.completion_tokens,
        request_id=body.request_id,
        recorded_at=body.recorded_at or now,
        metadata_=body.metadata_,
        create_user_id=actor.actor_id,
    )
    db.add(usage)
    await db.commit()

    return TokenUsageResponse.model_validate(_usage_to_response(usage))


@router.get(
    "/workers/{worker_id}/token-usage",
    response_model=CursorPage[TokenUsageResponse],
)
async def list_token_usage(
    worker_id: str,
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """查询某 Worker 的 token 消耗列表（游标分页，按 recorded_at 倒序）。"""
    # ── 验证 worker 存在 ──
    worker = await db.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError("worker", worker_id)

    # ── 构建查询 ──
    conditions = [TokenUsage.worker_id == worker_id]
    if cursor:
        conditions.append(TokenUsage.id < cursor)

    stmt = (
        select(TokenUsage)
        .where(*conditions)
        .order_by(TokenUsage.recorded_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = select(func.count(TokenUsage.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar()

    return CursorPage(
        items=[
            TokenUsageResponse.model_validate(_usage_to_response(u)) for u in items
        ],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/workers/{worker_id}/token-usage/stats")
async def get_token_usage_stats(
    worker_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """查询某 Worker 的 token 消耗聚合统计（总计 + 7 天日粒度）。"""
    worker = await db.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError("worker", worker_id)

    # ── 总计 ──
    totals = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0
                ),
                func.count(TokenUsage.id),
                func.count(func.distinct(TokenUsage.model)),
            ).where(TokenUsage.worker_id == worker_id)
        )
    ).one()

    total_tokens, total_requests, model_count = totals

    # ── Provider 分布 ──
    provider_rows = (
        await db.execute(
            select(
                TokenUsage.provider,
                func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens),
            )
            .where(TokenUsage.worker_id == worker_id)
            .group_by(TokenUsage.provider)
        )
    ).all()

    providers = {
        row[0]: row[1] for row in provider_rows if row[0]
    }

    # ── Model 分布（top 10）──
    model_rows = (
        await db.execute(
            select(
                TokenUsage.model,
                func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens),
            )
            .where(TokenUsage.worker_id == worker_id)
            .group_by(TokenUsage.model)
            .order_by(
                func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens).desc()
            )
            .limit(10)
        )
    ).all()

    models = {row[0]: row[1] for row in model_rows if row[0]}

    # ── 7 天日粒度 ──
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=6)
    daily_rows = (
        await db.execute(
            select(
                func.date(TokenUsage.recorded_at),
                func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens),
                func.count(TokenUsage.id),
            )
            .where(
                TokenUsage.worker_id == worker_id,
                TokenUsage.recorded_at >= seven_days_ago,
            )
            .group_by(func.date(TokenUsage.recorded_at))
            .order_by(func.date(TokenUsage.recorded_at))
        )
    ).all()

    daily = [
        {"date": str(row[0]), "tokens": row[1] or 0, "requests": row[2]}
        for row in daily_rows
    ]

    return {
        "worker_id": worker_id,
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "model_count": model_count,
        "providers": providers,
        "models": models,
        "daily": daily,
    }
