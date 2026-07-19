"""WebPush schemas — P10-B45 议题⑦ 前端订阅管理。

浏览器 PushSubscription 的 JSON 序列化格式参见 MDN:
  PushSubscription.toJSON() → { endpoint, keys: { p256dh, auth } }
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.schemas.common import AuditFields


class PushSubscriptionKeys(BaseModel):
    """浏览器 PushSubscription 密钥对（base64url 编码）。"""
    p256dh: str = Field(..., description="ECDH 公钥（base64url）")
    auth: str = Field(..., description="认证密钥（base64url）")


class PushSubscriptionCreate(BaseModel):
    """前端调用 subscribe() 后 POST 到后端的订阅信息。

    与浏览器 PushSubscription.toJSON() 输出一致。
    """
    endpoint: str = Field(..., description="推送服务 URL（如 fcm.googleapis.com）")
    keys: PushSubscriptionKeys
    device_info: str | None = Field(
        default=None,
        max_length=500,
        description="navigator.userAgent 等设备标识（可选）",
    )


class PushSubscriptionResponse(AuditFields):
    """返回给前端的订阅摘要。

    继承 AuditFields（is_disabled, create_user_id, ...）。
    注意：不返回 p256dh_key / auth_secret — 敏感数据不出 API。
    """
    id: str
    user_id: str
    endpoint: str
    device_info: str | None = None


class VapidPublicKeyInfo(BaseModel):
    """VAPID 公钥信息（前端 subscribe 时用作 applicationServerKey）。"""
    vapid_public_key: str
    vapid_claims_email: str
