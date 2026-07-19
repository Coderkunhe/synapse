"""Task continuity detection engine — identify unfinished work across sessions.

Adapted from GlassCortex SessionBoundaryDetector (src/context/session_boundary.py).
Key simplifications vs the GlassCortex original:

- Single data source (Event table) instead of three-tier fallback
  (pipeline_trace → plan_runs → episodes).  Synapse's Event ledger
  is the single source of truth for all activity.
- No open-question detection — Synapse has no conversation/episodes.
- async SQLAlchemy instead of sync raw SQLite.
- Stateless service pattern: methods receive ``db: AsyncSession``
  rather than holding a store reference.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.config import Settings, settings
from src.constants import TaskStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Non-terminal task statuses — tasks in any of these states are
# considered "unfinished" for continuity tracking purposes.
_UNFINISHED_STATUSES = frozenset({
    TaskStatus.BACKLOG,
    TaskStatus.READY,
    TaskStatus.IN_PROGRESS,
    TaskStatus.PAUSED,
    TaskStatus.IN_VERIFICATION,
    TaskStatus.REJECTED,
})


@dataclass
class ContinuityResult:
    """Result of a continuity detection run.

    Attributes:
        last_activity_at: Timestamp of the most recent Event in this project
            (None if no events exist = first check).
        last_activity_type: Event type string of the most recent event.
        unfinished_tasks: List of task dicts with non-terminal status.
        is_first_check: True when no prior ContinuitySnapshot exists for
            this project — indicates a fresh start with no history to
            compare against.
    """

    last_activity_at: datetime | None
    last_activity_type: str | None
    unfinished_tasks: list[dict[str, object]] = field(default_factory=list)
    is_first_check: bool = False


@dataclass
class ContinuitySummary:
    """Human-readable continuity summary comparing current state to history.

    Attributes:
        previous_snapshots: Historical ContinuitySnapshot rows (newest first).
        ongoing_tasks: Tasks that appear in BOTH current unfinished_tasks
            AND a prior snapshot — still not done.
        resolved_tasks: Tasks that appeared in a prior snapshot but are
            NO LONGER in current unfinished_tasks — now completed/cancelled.
        summary_text: Single-line Chinese summary for display.
    """

    previous_snapshots: list[dict[str, object]] = field(default_factory=list)
    ongoing_tasks: list[dict[str, object]] = field(default_factory=list)
    resolved_tasks: list[dict[str, object]] = field(default_factory=list)
    summary_text: str = ""


class TaskContinuityDetector:
    """Detect unfinished tasks and track continuity across checkpoints.

    Usage::

        detector = TaskContinuityDetector()
        result = await detector.detect(db, project_id)
        if result:
            await detector.save_snapshot(db, result, project_id)
            summary = await detector.generate_summary(db, result, project_id)
            await db.commit()
    """

    def __init__(self, config: Settings | None = None) -> None:
        """Initialize the detector.

        Args:
            config: Settings instance.  None → module-level singleton.
        """
        self._config = config or settings

    # ── Public API ─────────────────────────────────────────────────

    async def detect(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> ContinuityResult | None:
        """Run continuity detection for a project.

        Returns None when the feature flag is disabled or the last
        snapshot is fresher than ``snapshot_gap_seconds`` (i.e.
        still within the same "session").

        Args:
            db: Active async database session.
            project_id: Project to check continuity for.

        Returns:
            ContinuityResult if detection ran and found data;
            None if disabled or within the snapshot gap.
        """
        if not self._config.continuity.enabled:
            return None

        # ── Check snapshot gap ──────────────────────────────────
        last_snapshot = await self._get_latest_snapshot(db, project_id)
        now = datetime.now(timezone.utc)

        if last_snapshot is not None:
            last_ts = last_snapshot.get("created_at")
            if last_ts is not None:
                # Normalize: SQLite may return naive or aware depending
                # on how the row was inserted (ORM default vs raw SQL).
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                gap = (now - last_ts).total_seconds()
                if gap < self._config.continuity.snapshot_gap_seconds:
                    return None

        # ── Detect last activity ────────────────────────────────
        last_activity_at, last_activity_type = await self._detect_last_activity(
            db, project_id
        )

        # ── Detect unfinished tasks ─────────────────────────────
        unfinished = await self._detect_unfinished_tasks(db, project_id)

        is_first = last_snapshot is None

        return ContinuityResult(
            last_activity_at=last_activity_at,
            last_activity_type=last_activity_type,
            unfinished_tasks=unfinished,
            is_first_check=is_first,
        )

    async def generate_summary(
        self,
        db: AsyncSession,
        result: ContinuityResult,
        project_id: str,
        num_snapshots: int | None = None,
    ) -> ContinuitySummary:
        """Generate a continuity summary by comparing current state
        against historical snapshots.

        Args:
            db: Active async database session.
            result: The ContinuityResult from a prior detect() call.
            project_id: Project scope for snapshot lookup.
            num_snapshots: Number of historical snapshots to compare.
                None → use config default.

        Returns:
            ContinuitySummary with ongoing/resolved tasks and summary text.
        """
        n = (
            num_snapshots
            if num_snapshots is not None
            else self._config.continuity.num_snapshots_for_summary
        )
        recent = await self._get_recent_snapshots(db, project_id, n)

        # Build index of current unfinished task IDs
        current_ids: set[str] = {
            str(t.get("id", ""))
            for t in result.unfinished_tasks
            if t.get("id")
        }

        ongoing: list[dict[str, object]] = []
        resolved: list[dict[str, object]] = []
        seen_ongoing: set[str] = set()
        seen_resolved: set[str] = set()

        for prev in recent:
            prev_json = str(prev.get("unfinished_tasks_json", "[]"))
            try:
                prev_tasks: list[dict[str, object]] = json.loads(prev_json)
            except (json.JSONDecodeError, TypeError):
                prev_tasks = []

            for pt in prev_tasks:
                tid = str(pt.get("id", ""))
                if not tid:
                    continue
                if tid in current_ids:
                    if tid not in seen_ongoing:
                        ongoing.append(pt)
                        seen_ongoing.add(tid)
                elif tid not in seen_resolved:
                    resolved.append(pt)
                    seen_resolved.add(tid)

        summary_text = self._build_summary_text(ongoing, resolved, result)

        return ContinuitySummary(
            previous_snapshots=recent,
            ongoing_tasks=ongoing,
            resolved_tasks=resolved,
            summary_text=summary_text,
        )

    async def save_snapshot(
        self,
        db: AsyncSession,
        result: ContinuityResult,
        project_id: str,
    ) -> int:
        """Persist the current continuity state as a snapshot.

        Call this AFTER detect() returns a non-None result and BEFORE
        generate_summary() if you want the current state included in
        the historical comparison.

        Args:
            db: Active async database session.
            result: The ContinuityResult to persist.
            project_id: Project scope.

        Returns:
            The number of rows inserted (1).
        """
        from src.models.continuity import ContinuitySnapshot
        from src.utils.id_gen import generate_id

        last_activity_ts: float | None = None
        if result.last_activity_at is not None:
            last_activity_ts = result.last_activity_at.timestamp()

        snapshot = ContinuitySnapshot(
            id=generate_id("continuity_snapshot"),
            project_id=project_id,
            last_activity_at=last_activity_ts,
            unfinished_tasks_json=json.dumps(result.unfinished_tasks),
        )
        db.add(snapshot)
        return 1

    # ── Private detection methods ──────────────────────────────────

    async def _detect_last_activity(
        self, db: AsyncSession, project_id: str
    ) -> tuple[datetime | None, str | None]:
        """Find the most recent Event for a project.

        Synapse's Event ledger is the single source of truth — no
        multi-tier fallback needed (unlike GlassCortex which had to
        search pipeline_trace → plan_runs → episodes).

        Filters by project_id via a JOIN on Task (Event.target_id = Task.id
        when Event.target_type = 'task').
        """
        from src.models.event import Event
        from src.models.task import Task

        result = await db.execute(
            select(Event.created_at, Event.event_type)
            .join(Task, Event.target_id == Task.id)
            .where(
                Event.target_type == "task",
                Task.project_id == project_id,
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None, None
        ts: datetime = row[0]
        event_type: str = row[1]
        return ts, event_type

    async def _detect_unfinished_tasks(
        self, db: AsyncSession, project_id: str
    ) -> list[dict[str, object]]:
        """Find all tasks with non-terminal status in the project.

        Returns task dicts with id, title, status, priority, owner_type,
        owner_id — enough context for continuity display without
        pulling full payload.
        """
        from src.models.task import Task

        result = await db.execute(
            select(Task)
            .where(
                Task.project_id == project_id,
                Task.status.in_(_UNFINISHED_STATUSES),
            )
            .order_by(Task.priority, Task.created_at)
        )
        tasks = result.scalars().all()
        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "owner_type": t.owner_type,
                "owner_id": t.owner_id,
            }
            for t in tasks
        ]

    async def _get_latest_snapshot(
        self, db: AsyncSession, project_id: str
    ) -> dict[str, object] | None:
        """Get the most recent ContinuitySnapshot for a project."""
        from src.models.continuity import ContinuitySnapshot as CS

        result = await db.execute(
            select(CS)
            .where(CS.project_id == project_id)
            .order_by(CS.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id,
            "project_id": row.project_id,
            "last_activity_at": row.last_activity_at,
            "unfinished_tasks_json": row.unfinished_tasks_json,
            "created_at": row.created_at,
        }

    async def _get_recent_snapshots(
        self, db: AsyncSession, project_id: str, num: int
    ) -> list[dict[str, object]]:
        """Get the N most recent ContinuitySnapshots for a project."""
        from src.models.continuity import ContinuitySnapshot as CS

        result = await db.execute(
            select(CS)
            .where(CS.project_id == project_id)
            .order_by(CS.created_at.desc())
            .limit(num)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "project_id": r.project_id,
                "last_activity_at": r.last_activity_at,
                "unfinished_tasks_json": r.unfinished_tasks_json,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    @staticmethod
    def _build_summary_text(
        ongoing: list[dict[str, object]],
        resolved: list[dict[str, object]],
        result: ContinuityResult,
    ) -> str:
        """Build a human-readable Chinese summary string."""
        if result.is_first_check:
            return "这是首次检查，没有历史快照可供对比。"

        unfinished_count = len(result.unfinished_tasks)

        if unfinished_count == 0 and not ongoing and not resolved:
            return "所有任务已完成，没有遗留开放项。"

        parts: list[str] = []
        if unfinished_count:
            parts.append(f"{unfinished_count} 个未完成任务")
        if ongoing:
            parts.append(f"{len(ongoing)} 项持续未解决")
        if resolved:
            parts.append(f"{len(resolved)} 项已解决")

        return "，".join(parts) + "。"
