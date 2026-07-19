"""通知服务 — 统一通知抽象层。

P10-B33: 议题 ⑦ 通知通道 — Email 通道首次落地。
P10-B34: 议题 ⑦ 通知通道 — Webhook 通道 + L5 拉通补缺（expire/cancel WS push 对称）。
P10-B44: 议题 ⑦ 通知通道 — WebPush 后端（VAPID 浏览器推送）。
P10-B45: 议题 ⑦ 通知通道 — WebPush 前端（subscribe/unsubscribe 端点 + Service Worker）。

核心能力：
- notify_project_admins: 向 Project 所有 admin/lead 发送 Email 通知
- notify_webhook: 向 Project 配置的 webhook URL 发送 HTTP POST 事件
- notify_webpush: 向 Project 所有 admin/lead 浏览器发送 WebPush 通知

路由策略：
- Human admin (Worker.user_id → User.email 存在) → Email + WebPush 双通道
- Agent admin (Worker.user_id IS NULL) → 跳过（当前无 email/浏览器）
- Webhook URL 已配置 → HTTP POST 事件推送
- WS push to Admin → 远期

不在此层：
- WS push to Worker（已在 authorization_service 内联，B32/B34）
- 用户通知偏好（远期）

调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from string import Template

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.user import User
from src.models.worker import Worker
from src.services.email_service import send_email
from src.services.project_role_service import list_project_roles

logger = logging.getLogger(__name__)

# ── 模板 ──────────────────────────────────────────────────────────

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"


def _load_template(name: str) -> Template:
    """加载邮件模板文件。"""
    path = _TEMPLATE_DIR / name
    return Template(path.read_text(encoding="utf-8"))


# ── 查询辅助 ──────────────────────────────────────────────────────


async def _get_worker_name(db: AsyncSession, worker_id: str) -> str:
    """获取 Worker 的显示名。未找到返回 worker_id 本身。"""
    result = await db.execute(
        select(Worker.name).where(Worker.id == worker_id)
    )
    name = result.scalar_one_or_none()
    return name if name else worker_id


async def _get_user_email(db: AsyncSession, user_id: str) -> str | None:
    """获取 User 的 email。无 User 或 email 为空返回 None。"""
    result = await db.execute(
        select(User.email).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


# ── 通知发送 ──────────────────────────────────────────────────────


async def _send_auth_request_email(
    *,
    to_email: str,
    worker_name: str,
    request_type: str,
    operation: str | None,
    prompt_message: str | None,
    project_id: str,
) -> bool:
    """发送授权请求通知邮件给 admin。

    使用 auth_request_notification.html/.txt 模板。
    """
    request_type_label = (
        "Project Access"
        if request_type == "api_auth"
        else "Your Input"
    )

    # 构造邮件正文摘要
    if request_type == "api_auth":
        message = f"{worker_name} needs access to perform: {operation or 'an operation'}"
    else:
        message = prompt_message or f"{worker_name} needs your input"

    approvals_url = f"{settings.frontend_url}/approvals"

    html_template = _load_template("auth_request_notification.html")
    text_template = _load_template("auth_request_notification.txt")

    substitutes = {
        "worker_name": worker_name,
        "request_type_label": request_type_label,
        "operation": operation or "—",
        "prompt_message": message,
        "approvals_url": approvals_url,
        "project_id": project_id,
    }

    return await send_email(
        to_email=to_email,
        subject=f"Synapse — {request_type_label} Request from {worker_name}",
        html_body=html_template.substitute(substitutes),
        text_body=text_template.substitute(substitutes),
    )


# ── 公共 API ──────────────────────────────────────────────────────


async def notify_project_admins(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    request_type: str,
    operation: str | None = None,
    prompt_message: str | None = None,
) -> int:
    """通知 Project 的所有 admin/lead。

    对每个拥有 admin 或 lead 角色的 Worker：
    - 若 Worker 关联了 User 且 User 有 email → 发送邮件通知
    - 若 Worker 为 Agent（无 User）→ 跳过 email

    Returns:
        成功发送的邮件通知数。
    """
    # 获取请求方 Worker 名称
    worker_name = await _get_worker_name(db, worker_id)

    # 获取 Project 所有 admin/lead
    roles = await list_project_roles(db, project_id)
    admin_workers = [
        (worker, role)
        for worker, role in roles
        if role in ("admin", "lead")
    ]

    sent_count = 0

    for admin_worker, _role in admin_workers:
        # 不给请求方自己发通知
        if admin_worker.id == worker_id:
            continue

        # Agent admin — 无 email，跳过
        if admin_worker.user_id is None:
            continue

        email = await _get_user_email(db, admin_worker.user_id)
        if not email:
            logger.debug(
                "Admin worker %s has user %s but no email — skipping",
                admin_worker.id,
                admin_worker.user_id,
            )
            continue

        success = await _send_auth_request_email(
            to_email=email,
            worker_name=worker_name,
            request_type=request_type,
            operation=operation,
            prompt_message=prompt_message,
            project_id=project_id,
        )
        if success:
            sent_count += 1
        else:
            logger.warning(
                "Failed to send auth request email to %s (worker %s)",
                email,
                admin_worker.id,
            )

    if sent_count > 0:
        logger.info(
            "Sent %d auth request notification(s) for project %s (worker %s)",
            sent_count,
            project_id,
            worker_id,
        )

    return sent_count


# ── Webhook 通道 (P10-B34) ─────────────────────────────────────────


async def notify_webhook(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    request_type: str,
    request_id: str,
    operation: str | None = None,
    prompt_message: str | None = None,
) -> bool:
    """向 Project 配置的 webhook URL 发送 HTTP POST 事件。

    从 Project.webhook_url 读取目标 URL。
    未配置 webhook → 跳过，返回 False。
    HTTP POST 失败 → log warning，不抛异常。

    Fire-and-forget 模式：不阻断主流程。
    超时 10s，无重试（V1 最小可用版本）。

    Payload:
        {
            "event_type": "authorization_request.created",
            "project_id": "...",
            "worker_id": "...",
            "worker_name": "...",
            "request_type": "...",
            "operation": "...",
            "prompt_message": "...",
            "request_id": "...",
            "timestamp": "2026-07-18T..."
        }

    Returns:
        True 若 webhook 发送成功，False 若跳过或失败。
    """
    from src.models.project import Project

    # 读取 Project webhook_url
    result = await db.execute(
        select(Project.webhook_url).where(Project.id == project_id)
    )
    webhook_url = result.scalar_one_or_none()

    if not webhook_url:
        logger.debug("No webhook_url configured for project %s — skipping", project_id)
        return False

    # 获取 Worker 名称
    worker_name = await _get_worker_name(db, worker_id)

    payload: dict = {
        "event_type": "authorization_request.created",
        "project_id": project_id,
        "worker_id": worker_id,
        "worker_name": worker_name,
        "request_type": request_type,
        "operation": operation,
        "prompt_message": prompt_message,
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if 200 <= response.status_code < 300:
                logger.info(
                    "Webhook sent to %s for project %s (status %d)",
                    webhook_url,
                    project_id,
                    response.status_code,
                )
                return True
            else:
                logger.warning(
                    "Webhook to %s returned non-2xx status %d for project %s",
                    webhook_url,
                    response.status_code,
                    project_id,
                )
                return False
    except Exception:
        logger.exception(
            "Failed to send webhook to %s for project %s (worker %s)",
            webhook_url,
            project_id,
            worker_id,
        )
        return False


# ── WebPush 通道 (P10-B44 · S-066) ─────────────────────────────────


async def notify_webpush(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    request_type: str,
    operation: str | None = None,
    prompt_message: str | None = None,
    request_id: str = "",
) -> int:
    """向 Project 所有 admin/lead 的浏览器发送 WebPush 通知。

    查询 admin Worker → 关联 User → 读取 UserPushSubscription 表
    → 通过 pywebpush + VAPID 加密推送。

    VAPID 私钥未配置 → 静默跳过，返回 0。
    单条推送失败 → log warning，继续下一条（fire-and-forget）。

    Returns:
        成功发送的推送通知数。
    """
    import json

    from src.models.user_push_subscription import UserPushSubscription

    # VAPID 未配置 → 跳过
    if not settings.vapid_private_key or not settings.vapid_claims_email:
        logger.debug("VAPID not configured — skipping webpush")
        return 0

    # 获取请求方 Worker 名称
    worker_name = await _get_worker_name(db, worker_id)

    # 获取 Project 所有 admin/lead
    roles = await list_project_roles(db, project_id)
    admin_workers = [
        (worker, role)
        for worker, role in roles
        if role in ("admin", "lead")
    ]

    # 构建推送 payload
    push_payload = {
        "title": "Authorization Request",
        "body": f"{worker_name} requested {operation or request_type}",
        "icon": "/icons.svg",
        "data": {
            "request_id": request_id,
            "project_id": project_id,
            "request_type": request_type,
            "worker_id": worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }

    sent_count = 0

    for admin_worker, _role in admin_workers:
        # 不给请求方自己发通知
        if admin_worker.id == worker_id:
            continue

        # Agent admin 无 user_id → 跳过
        if admin_worker.user_id is None:
            continue

        # 查该 admin 的所有浏览器订阅
        result = await db.execute(
            select(UserPushSubscription).where(
                UserPushSubscription.user_id == admin_worker.user_id
            )
        )
        subscriptions = result.scalars().all()

        if not subscriptions:
            logger.debug(
                "Admin user %s has no push subscriptions — skipping webpush",
                admin_worker.user_id,
            )
            continue

        for sub in subscriptions:
            try:
                _send_webpush_notification(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh_key,
                            "auth": sub.auth_secret,
                        },
                    },
                    payload=push_payload,
                )
                sent_count += 1
            except Exception:
                logger.exception(
                    "Failed to send webpush to user %s endpoint %s",
                    admin_worker.user_id,
                    sub.endpoint[:80],
                )

    if sent_count > 0:
        logger.info(
            "Sent %d webpush notification(s) for project %s (worker %s)",
            sent_count,
            project_id,
            worker_id,
        )

    return sent_count


def _send_webpush_notification(
    *,
    subscription_info: dict,
    payload: dict,
) -> None:
    """通过 pywebpush 发送单条 WebPush 通知。

    提取为同步函数以便在线程池中执行（pywebpush 非 async-safe）。
    """
    import json

    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={
                "sub": f"mailto:{settings.vapid_claims_email}",
            },
        )
    except WebPushException as e:
        # 410 Gone → 订阅已过期，应清理但 V1 略过
        if hasattr(e, 'response') and e.response is not None and e.response.status_code == 410:
            logger.info(
                "WebPush subscription expired (410) for endpoint %s",
                subscription_info.get("endpoint", "")[:80],
            )
        else:
            raise
