"""Synapse FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from slowapi.middleware import SlowAPIMiddleware  # P100-B105 · PFL-085

from src.api.router import api_router
from src.api.routers.ws import websocket_endpoint
from src.config import limiter, settings  # P100-B105: limiter for rate limiting
from src.db import async_session_factory
from src.exceptions import SynapseError, synapse_error_handler
from src.services.authorization_service import expire_stale_requests
from src.services.lease_detector import release_expired_leases
from src.services.stale_task_detector import (
    detect_stale_tasks,
    detect_stale_verifications,
    detect_stale_verifications_escalation,
    detect_unclaimed_ready_tasks,
)
from src.services.ws_manager import ws_manager


# ── Background task: reap dead WebSocket connections ────────────────────────


async def _ws_reaper() -> None:
    """Periodically clean up timed-out WebSocket connections.

    P11-B128: aligned to spawn→check pattern — startup log + reap counter
    so health check can distinguish "never scanned" from "nothing reaped".
    """
    import logging
    _logger = logging.getLogger("synapse.ws_reaper")
    global _ws_reaper_reap_count

    while True:
        await asyncio.sleep(30)
        try:
            # P11-B128: startup log on first iteration
            if _ws_reaper_reap_count == 0:
                _logger.info("WS reaper started: interval=30s")

            count = await ws_manager.reap_dead_connections()
            _ws_reaper_reap_count += 1
            if count > 0:
                _logger.info("Reaped %d dead WS connection(s)", count)
        except Exception:
            _logger.warning(
                "WS reaper scan failed (will retry in 30s)",
                exc_info=True,
            )


# ── Background task: expire stale authorization requests (P11-B50) ──────────


async def _auth_expiry_reaper() -> None:
    """Periodically expire stale authorization requests.

    Calls expire_stale_requests() on its own DB session.
    Runs every auth_expiry_interval_seconds (default 30s).

    P11-B128: settings init moved inside try block (was outside, same
    silent-crash vulnerability as stale_reaper before B128 fix).
    Added startup log + expiry_counter for health check visibility.
    """
    import logging
    _logger = logging.getLogger("synapse.auth_reaper")
    global _auth_reaper_expiry_count

    while True:
        try:
            # P11-B128 (PFL-123 alignment): settings inside try —
            # prevents silent coroutine crash before entering the loop.
            interval = settings.auth_expiry_interval_seconds

            # P11-B128: startup log on first iteration
            if _auth_reaper_expiry_count == 0:
                _logger.info("Auth expiry reaper started: interval=%ds", interval)

            await asyncio.sleep(interval)
            async with async_session_factory() as db:
                count = await expire_stale_requests(db)
                await db.commit()
                _auth_reaper_expiry_count += 1
                if count > 0:
                    _logger.info("Expired %d stale authorization request(s)", count)
        except Exception:
            _logger.warning(
                "Auth expiry reaper scan failed (will retry in %ds)",
                settings.auth_expiry_interval_seconds,
                exc_info=True,
            )


# ── Background task: detect stale tasks and timed-out verifications ──────────


async def _stale_task_reaper() -> None:
    """Periodically scan for stale in_progress tasks (P11-B76)
    and timed-out in_verification tasks (P11-B88).

    P11-B125: adds reassign tier — abandoned in_progress tasks are
    unclaimed and returned to READY so another Worker can pick them up.

    P11-B128 (PFL-123): settings init moved inside try block — prevents
    silent coroutine crash where asyncio.create_task() returns a Task
    that never entered its while loop, fooling health check into
    reporting "running" when nothing is actually scanning.

    Calls detect_stale_tasks() and detect_stale_verifications()
    on their own DB session.
    Runs every task_stale_scan_interval_seconds (default 120s).
    """
    import logging
    _logger = logging.getLogger("synapse.stale_reaper")
    global _stale_reaper_scan_count

    while True:
        try:
            # P11-B128 (PFL-123): settings init inside try — any config
            # access error is caught and logged instead of silently
            # crashing the coroutine before the while loop.
            interval = settings.task_stale_scan_interval_seconds
            stale_threshold = settings.task_stale_threshold_minutes
            reassign_threshold = settings.task_stale_reassign_minutes
            verify_timeout = settings.verification_timeout_minutes
            escalation_minutes = settings.verification_escalation_minutes
            escalation_cooldown = settings.verification_escalation_cooldown_minutes

            # P11-B128 (PFL-123): startup log on first iteration — proves
            # the reaper actually entered its scan loop. Without this,
            # zero log lines could mean either "no stale tasks" or
            # "coroutine never started" — the two are indistinguishable.
            if _stale_reaper_scan_count == 0:
                _logger.info(
                    "Stale task reaper started: interval=%ds, stale=%dmin, "
                    "reassign=%dmin, verify_timeout=%dmin, "
                    "escalation=%dmin, escalation_cooldown=%dmin",
                    interval, stale_threshold, reassign_threshold,
                    verify_timeout, escalation_minutes, escalation_cooldown,
                )

            await asyncio.sleep(interval)
            async with async_session_factory() as db:
                # ── PFL-155: 每个 detector 独立 try/except —
                #     一个 flaky detector 不会回滚其他 detector 的工作

                # P11-B76 + P11-B125: stale in_progress detection + reassign
                try:
                    result = await detect_stale_tasks(
                        db,
                        threshold_minutes=stale_threshold,
                        reassign_threshold_minutes=reassign_threshold,
                    )
                except Exception:
                    _logger.warning(
                        "stale_tasks detector failed", exc_info=True,
                    )
                    result = {
                        "stale_count": 0, "stale_task_ids": [],
                        "cancelled_count": 0, "cancelled_task_ids": [],
                        "reassigned_count": 0, "reassigned_task_ids": [],
                        "reassigned_tasks": [],
                    }

                # P11-B88: verification timeout auto-reclaim
                try:
                    verify_result = await detect_stale_verifications(
                        db, threshold_minutes=verify_timeout,
                    )
                except Exception:
                    _logger.warning(
                        "stale_verifications detector failed", exc_info=True,
                    )
                    verify_result = {
                        "reverted_count": 0, "reverted_task_ids": [],
                        "cancelled_count": 0, "cancelled_task_ids": [],
                    }

                # P12-B47 (PFL-151 Option B): escalation to Human before auto-revert
                try:
                    escalation_result = await detect_stale_verifications_escalation(
                        db,
                        escalation_minutes=escalation_minutes,
                        revert_minutes=verify_timeout,
                        cooldown_minutes=escalation_cooldown,
                    )
                except Exception:
                    _logger.warning(
                        "verification_escalation detector failed", exc_info=True,
                    )
                    escalation_result = {
                        "escalated_count": 0, "escalated_task_ids": [],
                    }

                # P12-B25 (PFL-128): READY task unclaimed watchdog
                try:
                    ready_result = await detect_unclaimed_ready_tasks(
                        db,
                        threshold_minutes=settings.task_ready_unclaimed_timeout_minutes,
                    )
                except Exception:
                    _logger.warning(
                        "unclaimed_ready_tasks detector failed", exc_info=True,
                    )
                    ready_result = {
                        "unclaimed_count": 0, "unclaimed_task_ids": [],
                    }

                # P100-B157 (PFL-267): lease-expired task reclaim — release
                # lease-expired IN_PROGRESS tasks back to READY (live-worker guarded).
                try:
                    lease_result = await release_expired_leases(db)
                except Exception:
                    _logger.warning("lease_detector failed", exc_info=True)
                    lease_result = {"released_count": 0, "released_task_ids": []}

                await db.commit()

                # P11-B128 (PFL-123): increment scan counter so health
                # check can distinguish "never scanned" from "nothing found"
                _stale_reaper_scan_count += 1

                # B22: accumulate system intervention counters
                global _system_intervention_stale_detected, \
                    _system_intervention_stale_reassigned, \
                    _system_intervention_stale_cancelled, \
                    _system_intervention_verify_reverted, \
                    _system_intervention_verify_cancelled, \
                    _system_intervention_ready_unclaimed, \
                    _system_intervention_verify_escalated, \
                    _system_intervention_lease_released
                _system_intervention_stale_detected += result["stale_count"]
                _system_intervention_stale_reassigned += result.get("reassigned_count", 0)
                _system_intervention_stale_cancelled += result.get("cancelled_count", 0)
                _system_intervention_verify_reverted += verify_result["reverted_count"]
                _system_intervention_verify_cancelled += verify_result.get("cancelled_count", 0)
                _system_intervention_ready_unclaimed += ready_result["unclaimed_count"]
                _system_intervention_verify_escalated += escalation_result["escalated_count"]
                _system_intervention_lease_released += lease_result["released_count"]

                # ── WS broadcast for reassigned tasks (P11-B125) ──
                reassigned = result.get("reassigned_tasks", [])
                if reassigned:
                    logger = logging.getLogger("synapse")
                    logger.info(
                        "Reassigned %d abandoned task(s): %s",
                        len(reassigned),
                        [t["task_id"] for t in reassigned],
                    )
                    for rt in reassigned:
                        # Notify old owner that their task was reclaimed
                        old_owner = rt.get("old_owner_id")
                        if old_owner:
                            await ws_manager.broadcast_to_actor(
                                old_owner,
                                {
                                    "type": "event",
                                    "data": {
                                        "event_type": "task.lease_expired",
                                        "task_id": rt["task_id"],
                                        "reason": "stale_reassign",
                                        "message": (
                                            "Task was unclaimed due to inactivity. "
                                            "It has been returned to the ready pool."
                                        ),
                                    },
                                },
                            )

                if result["stale_count"] > 0 or result.get("cancelled_count", 0) > 0 or verify_result["reverted_count"] > 0 or verify_result.get("cancelled_count", 0) > 0 or escalation_result["escalated_count"] > 0:
                    logger = logging.getLogger("synapse")
                    if result["stale_count"] > 0:
                        logger.info(
                            "Detected %d stale task(s): %s",
                            result["stale_count"],
                            result["stale_task_ids"],
                        )
                    if result.get("cancelled_count", 0) > 0:
                        logger.info(
                            "Auto-cancelled %d stale task(s) after max detections: %s",
                            result["cancelled_count"],
                            result["cancelled_task_ids"],
                        )
                    if verify_result["reverted_count"] > 0:
                        logger.info(
                            "Auto-reverted %d timed-out verification(s): %s",
                            verify_result["reverted_count"],
                            verify_result["reverted_task_ids"],
                        )
                    if verify_result.get("cancelled_count", 0) > 0:
                        logger.info(
                            "Auto-cancelled %d task(s) after max revert retries: %s",
                            verify_result["cancelled_count"],
                            verify_result["cancelled_task_ids"],
                        )
                    if escalation_result["escalated_count"] > 0:
                        logger.info(
                            "Escalated %d verification(s) to Human (O SLA timeout): %s",
                            escalation_result["escalated_count"],
                            escalation_result["escalated_task_ids"],
                        )
        except Exception:
            _logger.warning(
                "Stale task reaper scan failed (will retry in %ds)",
                settings.task_stale_scan_interval_seconds,
                exc_info=True,
            )


# ── Background task: Worker heartbeat monitor (P11-B128 · PFL-126) ──────────


async def _worker_heartbeat_monitor() -> None:
    """Periodically scan for Workers with stale heartbeats → OFFLINE.

    P11-B128 (PFL-126 direction 4): This is the only system-level closed
    loop for heartbeat monitoring — it doesn't depend on AI prompt compliance.

    P12-B42: Provider-aware timeout — Codex CLI (no daemon, CronCreate-based
    heartbeat) gets 30 min grace period vs 5 min for persistent Workers.

    Scans all ACTIVE workers whose last_heartbeat_at is older than
    their provider-specific timeout, transitions them to OFFLINE runtime
    status, and records worker.runtime.offline events.
    """
    import logging
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select as sa_select
    from src.constants import ActorType, WorkerRuntimeStatus, WorkerStatus
    from src.models.worker import Worker
    from src.services.event_store import event_store
    from src.worker_state_machine import apply_transition

    _logger = logging.getLogger("synapse.heartbeat_monitor")
    global _heartbeat_monitor_scan_count

    while True:
        try:
            # P11-B128: settings inside try — prevents silent coroutine crash
            interval = settings.worker_heartbeat_monitor_interval_seconds
            standard_timeout = settings.worker_heartbeat_timeout_seconds
            codex_timeout = settings.worker_heartbeat_timeout_seconds_codex

            if _heartbeat_monitor_scan_count == 0:
                _logger.info(
                    "Worker heartbeat monitor started: interval=%ds, "
                    "standard_timeout=%ds, codex_timeout=%ds",
                    interval, standard_timeout, codex_timeout,
                )

            await asyncio.sleep(interval)

            async with async_session_factory() as db:
                now = datetime.now(timezone.utc)

                # P12-B45 (PFL-144): 扩展扫描到 ACTIVE + PENDING —
                # Codex Worker 可能在 PENDING 状态通过 CronCreate 发送心跳，
                # 仅扫 ACTIVE 会导致其不可见。
                # Provider-specific timeout applied in Python (P12-B42).
                stmt = sa_select(Worker).where(
                    Worker.status.in_([WorkerStatus.ACTIVE, WorkerStatus.PENDING]),
                    Worker.runtime_status != WorkerRuntimeStatus.OFFLINE,
                    Worker.last_heartbeat_at.is_not(None),
                )
                result = await db.execute(stmt)
                candidates = result.scalars().all()

                offline_count = 0
                for worker in candidates:
                    # P12-B42: provider-specific timeout
                    timeout = (
                        codex_timeout
                        if worker.provider == "codex"
                        else standard_timeout
                    )
                    cutoff = now - timedelta(seconds=timeout)

                    last_hb = worker.last_heartbeat_at
                    if last_hb is None:
                        continue
                    if last_hb.tzinfo is None:
                        last_hb = last_hb.replace(tzinfo=timezone.utc)

                    if last_hb >= cutoff:
                        continue  # still within provider-specific grace period

                    age_seconds = int((now - last_hb).total_seconds())

                    event_type, payload = apply_transition(
                        worker,
                        WorkerRuntimeStatus.OFFLINE,
                        actor_type=ActorType.SYSTEM,
                        actor_id="system",
                        context={
                            "reason": "heartbeat_timeout",
                            "last_heartbeat_age_seconds": age_seconds,
                            "timeout_seconds": timeout,
                            "provider": worker.provider,
                        },
                    )
                    await event_store.record(
                        db,
                        event_type=event_type,
                        team_id=worker.team_id,
                        actor_type=ActorType.SYSTEM,
                        actor_id="system",
                        target_type="worker",
                        target_id=worker.id,
                        payload=payload,
                    )

                    # WS notify the worker that they're now offline
                    await ws_manager.broadcast_to_actor(
                        worker.id,
                        {
                            "type": "event",
                            "data": {
                                "event_type": "worker.runtime.offline",
                                "worker_id": worker.id,
                                "reason": "heartbeat_timeout",
                                "last_heartbeat_age_seconds": age_seconds,
                            },
                        },
                    )

                    _logger.warning(
                        "Worker %s (%s provider=%s) marked OFFLINE: "
                        "last heartbeat %ds ago (timeout=%ds)",
                        worker.id, worker.name, worker.provider,
                        age_seconds, timeout,
                    )
                    offline_count += 1

                await db.commit()
                _heartbeat_monitor_scan_count += 1
                # P12-B45 (PFL-144): accumulate offline detections for /health visibility
                global _heartbeat_monitor_offline_count
                _heartbeat_monitor_offline_count += offline_count

                if offline_count > 0:
                    _logger.info(
                        "Heartbeat monitor: marked %d worker(s) OFFLINE (scan #%d, total=%d)",
                        offline_count, _heartbeat_monitor_scan_count,
                        _heartbeat_monitor_offline_count,
                    )

        except Exception:
            _logger.warning(
                "Heartbeat monitor scan failed (will retry in %ds)",
                settings.worker_heartbeat_monitor_interval_seconds,
                exc_info=True,
            )


_reaper_task: asyncio.Task | None = None
_expiry_reaper_task: asyncio.Task | None = None
_stale_reaper_task: asyncio.Task | None = None
_stale_reaper_scan_count: int = 0  # P11-B128 (PFL-123): proves reaper is actually scanning
_ws_reaper_reap_count: int = 0  # P11-B128: proves WS reaper is actually scanning
_auth_reaper_expiry_count: int = 0  # P11-B128: proves auth reaper is actually scanning
_heartbeat_monitor_task: asyncio.Task | None = None  # P11-B128: heartbeat monitor handle
_heartbeat_monitor_scan_count: int = 0  # P11-B128: proves heartbeat monitor is scanning
_heartbeat_monitor_offline_count: int = 0  # P12-B45 (PFL-144): workers marked OFFLINE by heartbeat monitor

# B22: system intervention counters — emergency system actions that indicate
# potential DB bypass risk. Accumulated across server lifetime, reported in
# /health for monitoring trend (rising = more problems = more bypass needed).
_system_intervention_stale_detected: int = 0
_system_intervention_stale_reassigned: int = 0
_system_intervention_stale_cancelled: int = 0
_system_intervention_verify_reverted: int = 0
_system_intervention_verify_cancelled: int = 0
_system_intervention_ready_unclaimed: int = 0  # P12-B25 (PFL-128)
_system_intervention_verify_escalated: int = 0  # P12-B47 (PFL-151 Option B)
_system_intervention_lease_released: int = 0  # P100-B157 (PFL-267)


# ── PFL-154: system worker bootstrap ─────────────────────────────────────────


async def _ensure_system_worker() -> None:
    """Create the SYSTEM pseudo-worker if it doesn't exist (P12-B49 · PFL-154).

    The escalation detector (and other system actors) need ``sender_worker_id``
    to satisfy the FK constraint on ``task_worker_conversation.sender_worker_id``.
    Without a "system" worker, ``create_message(sender_worker_id="system")`` fails
    with IntegrityError — which B48-1 mitigates via savepoint, but the @Human
    message is still lost.

    This is Option A from PFL-154: seed a system worker at startup rather than
    altering the FK constraint (Option B would require an Alembic migration).
    """
    from sqlalchemy import select as sa_select
    from src.models.worker import Worker

    async with async_session_factory() as db:
        result = await db.execute(
            sa_select(Worker.id).where(Worker.id == "system"),
        )
        if result.first() is not None:
            return  # Already exists

        system_worker = Worker(
            id="system",
            name="System",
            provider="system",
            status="active",
            team_id=None,
        )
        db.add(system_worker)
        await db.commit()

        import logging
        logging.getLogger("synapse").info("Created system worker (PFL-154)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    global _reaper_task, _expiry_reaper_task, _stale_reaper_task, _heartbeat_monitor_task
    # P12-B49 (PFL-154): ensure system worker exists before daemons that
    # may create messages with sender_worker_id="system"
    await _ensure_system_worker()
    _reaper_task = asyncio.create_task(_ws_reaper())
    _expiry_reaper_task = asyncio.create_task(_auth_expiry_reaper())
    _stale_reaper_task = asyncio.create_task(_stale_task_reaper())
    _heartbeat_monitor_task = asyncio.create_task(_worker_heartbeat_monitor())
    # P11-B128 (PFL-123): verify all daemon coroutines actually started —
    # if settings init or any pre-loop code raised, the Task is done() with
    # an exception but health check would report "running" (done()=False
    # only means the coroutine hasn't been awaited, not that it's alive).
    await asyncio.sleep(0.1)
    daemon_tasks = [
        ("ws_reaper", _reaper_task),
        ("auth_reaper", _expiry_reaper_task),
        ("stale_reaper", _stale_reaper_task),
        ("heartbeat_monitor", _heartbeat_monitor_task),
    ]
    for name, task in daemon_tasks:
        if task.done():
            exc = task.exception()
            if exc:
                import logging
                logging.getLogger("synapse").error(
                    "%s crashed on startup: %s", name, exc,
                    exc_info=True,
                )
    yield
    # P11-B23: 优雅关闭 — 通知所有 WS 客户端后断开
    await ws_manager.graceful_shutdown()
    if _reaper_task:
        _reaper_task.cancel()
        try:
            await _reaper_task
        except asyncio.CancelledError:
            pass
    if _expiry_reaper_task:
        _expiry_reaper_task.cancel()
        try:
            await _expiry_reaper_task
        except asyncio.CancelledError:
            pass
    if _stale_reaper_task:
        _stale_reaper_task.cancel()
        try:
            await _stale_reaper_task
        except asyncio.CancelledError:
            pass
    if _heartbeat_monitor_task:
        _heartbeat_monitor_task.cancel()
        try:
            await _heartbeat_monitor_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Synapse",
        description="Human-AI hybrid team coordination platform",
        version="0.1.0",
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True},
    )

    # CORS — credentials required for httpOnly cookie auth
    # allow_origins must be specific origins when allow_credentials=True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting (P100-B105 · PFL-085)
    if settings.rate_limit_enabled:
        app.state.limiter = limiter
        app.add_middleware(SlowAPIMiddleware)

    # Structured error handling (protocol.md §9)
    app.add_exception_handler(SynapseError, synapse_error_handler)

    # Health check (no auth required)
    @app.get("/health")
    async def health():
        # Health check — reaper status diagnostics (B115 PFL-119)
        def _reaper_status(task):
            """Return 'running' | 'not_started' | 'crashed: <reason>'."""
            if not task:
                return "not_started"
            if not task.done():
                return "running"
            exc = task.exception()
            return f"crashed: {exc}" if exc else "completed"

        return {
            "status": "ok",
            "ws_connections": ws_manager.connection_count,
            "reapers": {
                # P11-B128: all daemons expose status + counter —
                # "running" alone is misleading when a coroutine
                # crashed silently (un-awaited Task reports done()=False).
                "ws_reaper": {
                    "status": _reaper_status(_reaper_task),
                    "reap_count": _ws_reaper_reap_count,
                },
                "auth_reaper": {
                    "status": _reaper_status(_expiry_reaper_task),
                    "expiry_count": _auth_reaper_expiry_count,
                },
                "stale_reaper": {
                    "status": _reaper_status(_stale_reaper_task),
                    "scan_count": _stale_reaper_scan_count,
                },
                "heartbeat_monitor": {
                    "status": _reaper_status(_heartbeat_monitor_task),
                    "scan_count": _heartbeat_monitor_scan_count,
                    "offline_count": _heartbeat_monitor_offline_count,  # P12-B45 (PFL-144)
                },
            },
            # B22: system intervention counters — accumulated across server
            # lifetime. Rising trends correlate with God's-eye DB bypass risk.
            "system_interventions": {
                "stale_detected": _system_intervention_stale_detected,
                "stale_reassigned": _system_intervention_stale_reassigned,
                "stale_cancelled": _system_intervention_stale_cancelled,
                "verify_reverted": _system_intervention_verify_reverted,
                "verify_cancelled": _system_intervention_verify_cancelled,
                "ready_unclaimed": _system_intervention_ready_unclaimed,
                "verify_escalated": _system_intervention_verify_escalated,
                "lease_released": _system_intervention_lease_released,
            },
        }

    # WebSocket endpoint — registered directly on app (not through nested router)
    # to avoid Starlette routing issues with WebSocket upgrades
    app.add_api_websocket_route("/v1/ws", websocket_endpoint)

    # API routes
    app.include_router(api_router)

    return app


app = create_app()


# ── OpenAPI customisation: Bearer token security scheme for Swagger UI (PFL-040) ──


def _custom_openapi():
    """Inject Bearer token security scheme so Swagger UI shows an Authorize button."""
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {})["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT or API Key",
            "description": "JWT token from /v1/auth/login, or Worker API Key (sk-syn-…)",
        }
    }
    # NOTE: No global "security" — declaring the scheme is enough for the
    # Authorize button to appear. Unauthenticated endpoints (/health,
    # /v1/auth/login, etc.) stay lock-free.
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = _custom_openapi
