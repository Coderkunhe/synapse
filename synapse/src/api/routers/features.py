"""Feature flags endpoint — public config for UI mode switching (S-015 极简模式)."""

from fastapi import APIRouter

from src.config import settings

router = APIRouter(tags=["features"])


@router.get("/features")
async def get_features() -> dict:
    """Return feature flags controlling UI complexity.

    No auth required — public config, like /health.
    """
    return {
        "project_count": settings.features.project_count,
        "batch_size": settings.features.batch_size,
        "teams": settings.features.teams,
    }
