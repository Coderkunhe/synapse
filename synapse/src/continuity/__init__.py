"""Task continuity detection — cross-session unfinished task tracking.

Adapted from GlassCortex SessionBoundaryDetector (audit R2) and
simplified for Synapse's async SQLAlchemy + Event ledger data model.
"""

from src.continuity.detector import (
    ContinuityResult,
    ContinuitySummary,
    TaskContinuityDetector,
)

__all__ = [
    "ContinuityResult",
    "ContinuitySummary",
    "TaskContinuityDetector",
]
