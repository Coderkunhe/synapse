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
from src.services.stale_task_detector import detect_stale_tasks, detect_stale_verifications
from src.services.ws_manager import ws_manager


# ── Background task: reap dead WebSocket connections ────────────────────────


async def _ws_reaper() -> None:
    """Periodically clean up timed-out WebSocket connections."""
    while True:
        await asyncio.sleep(30)
        try:
            await ws_manager.reap_dead_connections()
        except Exception:
            import logging
            logging.getLogger("synapse.ws_reaper").warning(
                "WS reaper scan failed (will retry in 30s)",
                exc_info=True,
            )


# ── Background task: expire stale authorization requests (P11-B50) ──────────


async def _auth_expiry_reaper() -> None:
    """Periodically expire stale authorization requests.

    Calls expire_stale_requests() on its own DB session.
    Runs every auth_expiry_interval_seconds (default 30s).
    """
    import logging
    _logger = logging.getLogger("synapse.auth_reaper")
    interval = settings.auth_expiry_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session_factory() as db:
                count = await expire_stale_requests(db)
                await db.commit()
                if count > 0:
                    _logger.info("Expired %d stale authorization request(s)", count)
        except Exception:
            _logger.warning(
                "Auth expiry reaper scan failed (will retry in %ds)",
                interval,
                exc_info=True,
            )


# ── Background task: detect stale tasks and timed-out verifications ──────────


async def _stale_task_reaper() -> None:
    """Periodically scan for stale in_progress tasks (P11-B76)
    and timed-out in_verification tasks (P11-B88).

    Calls detect_stale_tasks() and detect_stale_verifications()
    on their own DB session.
    Runs every task_stale_scan_interval_seconds (default 120s).
    """
    interval = settings.task_stale_scan_interval_seconds
    stale_threshold = settings.task_stale_threshold_minutes
    verify_timeout = settings.verification_timeout_minutes
    while True:
        try:
            await asyncio.sleep(interval)
            async with async_session_factory() as db:
                # P11-B76: stale in_progress detection
                result = await detect_stale_tasks(db, threshold_minutes=stale_threshold)
                # P11-B88: verification timeout auto-reclaim
                verify_result = await detect_stale_verifications(
                    db, threshold_minutes=verify_timeout,
                )
                await db.commit()
                if result["stale_count"] > 0 or result.get("cancelled_count", 0) > 0 or verify_result["reverted_count"] > 0 or verify_result.get("cancelled_count", 0) > 0:
                    import logging
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
        except Exception:
            _logger = logging.getLogger("synapse.stale_reaper")
            _logger.warning(
                "Stale task reaper scan failed (will retry in %ds)",
                interval,
                exc_info=True,
            )


_reaper_task: asyncio.Task | None = None
_expiry_reaper_task: asyncio.Task | None = None
_stale_reaper_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    global _reaper_task, _expiry_reaper_task, _stale_reaper_task
    _reaper_task = asyncio.create_task(_ws_reaper())
    _expiry_reaper_task = asyncio.create_task(_auth_expiry_reaper())
    _stale_reaper_task = asyncio.create_task(_stale_task_reaper())
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
                "ws_reaper": _reaper_status(_reaper_task),
                "auth_reaper": _reaper_status(_expiry_reaper_task),
                "stale_reaper": _reaper_status(_stale_reaper_task),
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
