"""Synapse FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.router import api_router
from src.api.routers.ws import websocket_endpoint
from src.config import settings
from src.exceptions import SynapseError, synapse_error_handler
from src.services.ws_manager import ws_manager


# ── Background task: reap dead WebSocket connections ────────────────────────


async def _ws_reaper() -> None:
    """Periodically clean up timed-out WebSocket connections."""
    while True:
        await asyncio.sleep(30)
        try:
            await ws_manager.reap_dead_connections()
        except Exception:
            pass


_reaper_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    global _reaper_task
    _reaper_task = asyncio.create_task(_ws_reaper())
    yield
    if _reaper_task:
        _reaper_task.cancel()
        try:
            await _reaper_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Synapse",
        description="Human-AI hybrid team coordination platform",
        version="0.1.0",
        lifespan=lifespan,
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

    # Structured error handling (protocol.md §9)
    app.add_exception_handler(SynapseError, synapse_error_handler)

    # Health check (no auth required)
    @app.get("/health")
    async def health():
        return {"status": "ok", "ws_connections": ws_manager.connection_count}

    # WebSocket endpoint — registered directly on app (not through nested router)
    # to avoid Starlette routing issues with WebSocket upgrades
    app.add_api_websocket_route("/v1/ws", websocket_endpoint)

    # API routes
    app.include_router(api_router)

    return app


app = create_app()
