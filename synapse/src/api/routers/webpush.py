"""WebPush API 路由 — P10-B45 议题⑦ 前端订阅管理。

端点：
- GET  /webpush/vapid-public-key    # 公开 — 返回 VAPID 公钥
- POST /webpush/subscribe           # 登录用户 — 保存浏览器订阅
- DELETE /webpush/subscribe         # 登录用户 — 取消订阅（软删除）
- GET  /webpush/subscriptions       # 登录用户 — 列出当前订阅
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import ForbiddenError, NotFoundError
from src.models.user_push_subscription import UserPushSubscription
from src.schemas.webpush import (
    PushSubscriptionCreate,
    PushSubscriptionResponse,
    VapidPublicKeyInfo,
)
from src.utils.id_gen import generate_id

router = APIRouter(prefix="/webpush", tags=["webpush"])


# ── Helpers ──────────────────────────────────────────────────────────


def _ensure_human(actor: ActorInfo) -> str:
    """校验当前用户是人类并返回 user_id。Worker（API key auth）的 user_id 为 None。"""
    if not actor.user_id:
        raise ForbiddenError(
            "WEBPUSH_HUMAN_ONLY",
            "Only human users can manage push subscriptions",
        )
    return actor.user_id


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/vapid-public-key", response_model=VapidPublicKeyInfo)
async def get_vapid_public_key() -> VapidPublicKeyInfo:
    """返回 VAPID 公钥 — 前端 PushManager.subscribe() 需要。

    公钥非敏感信息，无需认证。
    """
    return VapidPublicKeyInfo(
        vapid_public_key=settings.vapid_public_key,
        vapid_claims_email=settings.vapid_claims_email,
    )


@router.post("/subscribe", response_model=PushSubscriptionResponse, status_code=201)
async def subscribe_push(
    body: PushSubscriptionCreate,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> PushSubscriptionResponse:
    """保存或更新浏览器推送订阅。

    同一用户 + 同一 endpoint → upsert（更新 keys + device_info，恢复 is_disabled）。
    """
    user_id = _ensure_human(actor)

    # Upsert: 查现有订阅
    result = await db.execute(
        select(UserPushSubscription).where(
            UserPushSubscription.user_id == user_id,
            UserPushSubscription.endpoint == body.endpoint,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # 更新密钥和设备信息，恢复已禁用的订阅
        existing.p256dh_key = body.keys.p256dh
        existing.auth_secret = body.keys.auth
        existing.device_info = body.device_info or existing.device_info
        existing.is_disabled = False
        sub = existing
    else:
        sub = UserPushSubscription(
            id=generate_id("user_push_subscription"),
            user_id=user_id,
            endpoint=body.endpoint,
            p256dh_key=body.keys.p256dh,
            auth_secret=body.keys.auth,
            device_info=body.device_info,
        )
        db.add(sub)

    await db.commit()
    await db.refresh(sub)

    return PushSubscriptionResponse.model_validate(sub)


@router.delete("/subscribe", status_code=204)
async def unsubscribe_push(
    body: dict,  # { endpoint: str } — 简单 dict 避免 schema 文件多余类
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> None:
    """取消浏览器推送订阅（软删除：is_disabled=True）。

    Body: {"endpoint": "https://fcm.googleapis.com/..."}
    """
    user_id = _ensure_human(actor)
    endpoint = body.get("endpoint", "")

    result = await db.execute(
        select(UserPushSubscription).where(
            UserPushSubscription.user_id == user_id,
            UserPushSubscription.endpoint == endpoint,
        )
    )
    sub = result.scalar_one_or_none()

    if sub is None:
        raise NotFoundError(
            "SUBSCRIPTION_NOT_FOUND",
            f"No push subscription found for endpoint: {endpoint[:80]}",
        )

    sub.is_disabled = True
    await db.commit()
    # 204 — 不返回 body


@router.get("/subscriptions", response_model=list[PushSubscriptionResponse])
async def list_subscriptions(
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[PushSubscriptionResponse]:
    """列出当前用户所有有效（未禁用）的推送订阅。"""
    user_id = _ensure_human(actor)

    result = await db.execute(
        select(UserPushSubscription).where(
            UserPushSubscription.user_id == user_id,
            UserPushSubscription.is_disabled == False,  # noqa: E712
        )
    )
    subs = result.scalars().all()

    return [PushSubscriptionResponse.model_validate(s) for s in subs]
