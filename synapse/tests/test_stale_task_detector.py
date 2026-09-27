"""P11-B76/B88/B108: stale task 检测器单元测试 — detect_stale_tasks + detect_stale_verifications + auto-cancel gate。
P12-B25 (PFL-128): READY task 无人认领检测测试。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, TaskStatus, WorkerStatus
from src.db import async_session_factory
from src.models.event import Event
from src.models.project import Project
from src.models.task import Task
from src.models.team import Team
from src.models.worker import Worker
from src.services.event_store import event_store
from src.services.stale_task_detector import (
    detect_stale_tasks,
    detect_stale_verifications,
    detect_unclaimed_ready_tasks,
)
from src.utils.id_gen import generate_id


class TestStaleTaskDetector:
    """P11-B76/B88: stale task 检测器单元测试。"""

    @pytest.mark.asyncio
    async def test_detect_stale_in_progress_tasks(self):
        """P11-B125: in_progress > reassign_threshold → unclaim + READY（回收层）。

        旧行为（B76）仅记 stale_detected 事件。B125 新增回收层：
        in_progress 任务超过 reassign_threshold（默认 15min）→ 自动 unclaim
        归还到 READY 池。PAUSED 任务不受影响（主动暂停≠被遗弃）。
        """
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-stale"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-stale"))
            await db.flush()

            # Create a stale task (updated_at 2 hours ago → should be reassigned)
            stale_task = Task(
                id="tsk_stale_001",
                project_id=project_id,
                title="Stale Task",
                description="This task has been in_progress too long",
                status=TaskStatus.IN_PROGRESS,
                owner_type="worker",
                owner_id="ag_stale_001",
            )
            stale_task.claimed_at = datetime.now(timezone.utc) - timedelta(hours=2)
            stale_task.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
            db.add(stale_task)

            # Create a fresh task (updated_at recently → no action)
            fresh_task = Task(
                id="tsk_fresh_001",
                project_id=project_id,
                title="Fresh Task",
                description="This task is actively being worked on",
                status=TaskStatus.IN_PROGRESS,
                owner_type="worker",
                owner_id="ag_fresh_001",
            )
            fresh_task.claimed_at = datetime.now(timezone.utc)
            fresh_task.updated_at = datetime.now(timezone.utc)
            db.add(fresh_task)
            await db.flush()

            # Run detector — stale task should be reassigned (not just logged)
            result = await detect_stale_tasks(
                db, threshold_minutes=60, reassign_threshold_minutes=15,
            )
            # 断言聚焦本测试自己的任务 —— detect_stale_tasks 是全局扫描，
            # 共享 DB 里的其它残留 in_progress 任务会干扰精确 count（P16-B7 PFL-262）。
            assert "tsk_stale_001" in result["reassigned_task_ids"]
            assert "tsk_fresh_001" not in result["reassigned_task_ids"]
            assert "tsk_stale_001" not in result["stale_task_ids"]
            assert "tsk_stale_001" not in result["cancelled_task_ids"]

            # Verify task was actually unclaimed and returned to READY
            await db.flush()
            await db.refresh(stale_task)
            assert stale_task.status == TaskStatus.READY
            assert stale_task.owner_type is None
            assert stale_task.owner_id is None
            assert stale_task.claimed_at is None

            # Fresh task unaffected
            await db.refresh(fresh_task)
            assert fresh_task.status == TaskStatus.IN_PROGRESS

            await db.rollback()

    # ── P16-B7 (PFL-262): reassign gated on owner worker alive ──

    @pytest.mark.asyncio
    async def test_stale_task_not_reassigned_when_owner_worker_alive(self):
        """PFL-262: IN_PROGRESS 任务 stale 但 owner worker 心跳新鲜 → 不回收。

        不回收也不记 stale 事件（跳过）—— 回收应以「worker 是否失联」
        为准，不以「task 是否有进度」为准（PFL-245 候选③）。
        """
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-stale-alive"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-alive"))
            await db.flush()

            worker_id = "ag_alive_001"
            # owner worker 心跳新鲜（存活）—— 长任务期间 driver keepalive 持续刷新
            db.add(Worker(
                id=worker_id,
                team_id=team_id,
                name="Alive Worker",
                provider="claude",
                status=WorkerStatus.ACTIVE,
                last_heartbeat_at=datetime.now(timezone.utc),
            ))

            stale_task = Task(
                id="tsk_alive_001",
                project_id=project_id,
                title="Alive But Slow Task",
                description="Owner is alive, just slow",
                status=TaskStatus.IN_PROGRESS,
                owner_type="worker",
                owner_id=worker_id,
            )
            stale_task.claimed_at = datetime.now(timezone.utc) - timedelta(hours=2)
            stale_task.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
            db.add(stale_task)
            await db.flush()

            result = await detect_stale_tasks(
                db, threshold_minutes=60, reassign_threshold_minutes=45,
            )
            assert result["reassigned_count"] == 0
            assert result["stale_count"] == 0   # 存活 worker → 跳过，不回收也不记 stale
            assert "tsk_alive_001" not in result["stale_task_ids"]

            await db.flush()
            await db.refresh(stale_task)
            assert stale_task.status == TaskStatus.IN_PROGRESS
            assert stale_task.owner_id == worker_id

            await db.rollback()

    @pytest.mark.asyncio
    async def test_stale_task_not_reassigned_when_owner_human(self):
        """P17-B2 (PFL-245): IN_PROGRESS 任务 stale 但 owner 是 human → 不回收。

        人类认领者没有心跳/续期机制，「无进度」不代表「失联」→ lease/stale
        回收不适用（免死）。不回收也不记 stale 事件。
        """
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-stale-human"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-human"))
            await db.flush()

            stale_task = Task(
                id="tsk_human_001",
                project_id=project_id,
                title="Human Owned Task",
                description="Owner is a human, no heartbeat to check",
                status=TaskStatus.IN_PROGRESS,
                owner_type="human",
                owner_id="human_001",
            )
            stale_task.claimed_at = datetime.now(timezone.utc) - timedelta(hours=2)
            stale_task.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
            db.add(stale_task)
            await db.flush()

            result = await detect_stale_tasks(
                db, threshold_minutes=60, reassign_threshold_minutes=15,
            )
            assert "tsk_human_001" not in result["reassigned_task_ids"]
            assert "tsk_human_001" not in result["stale_task_ids"]

            await db.flush()
            await db.refresh(stale_task)
            assert stale_task.status == TaskStatus.IN_PROGRESS
            assert stale_task.owner_type == "human"
            assert stale_task.owner_id == "human_001"

            await db.rollback()

    @pytest.mark.asyncio
    async def test_stale_task_reassigned_when_owner_worker_dead(self):
        """PFL-262: IN_PROGRESS 任务 stale 且 owner worker 心跳过期 → 回收。

        owner worker 真失联（last_heartbeat_at 超过 provider 阈值）→ 维持
        原有 unclaim 行为。
        """
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-stale-dead"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-dead"))
            await db.flush()

            worker_id = "ag_dead_001"
            db.add(Worker(
                id=worker_id,
                team_id=team_id,
                name="Dead Worker",
                provider="claude",
                status=WorkerStatus.ACTIVE,
                last_heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ))

            stale_task = Task(
                id="tsk_dead_001",
                project_id=project_id,
                title="Dead Worker Task",
                description="Owner worker is gone",
                status=TaskStatus.IN_PROGRESS,
                owner_type="worker",
                owner_id=worker_id,
            )
            stale_task.claimed_at = datetime.now(timezone.utc) - timedelta(hours=2)
            stale_task.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
            db.add(stale_task)
            await db.flush()

            result = await detect_stale_tasks(
                db, threshold_minutes=60, reassign_threshold_minutes=45,
            )
            assert result["reassigned_count"] == 1
            assert "tsk_dead_001" in result["reassigned_task_ids"]

            await db.flush()
            await db.refresh(stale_task)
            assert stale_task.status == TaskStatus.READY
            assert stale_task.owner_id is None

            await db.rollback()

    # ── B90: PAUSED stale detection ──

    @pytest.mark.asyncio
    async def test_detect_stale_paused_tasks(self):
        """PAUSED 任务过期 → 也检测为 stale（B90 补缺）。"""
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-stale-paused"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-stale-paused"))
            await db.flush()

            stale_paused = Task(
                id="tsk_stale_paused_001",
                project_id=project_id,
                title="Stale Paused Task",
                description="Paused and abandoned",
                status=TaskStatus.PAUSED,
                owner_type="worker",
                owner_id="ag_stale_001",
            )
            stale_paused.claimed_at = datetime.now(timezone.utc) - timedelta(hours=3)
            stale_paused.updated_at = datetime.now(timezone.utc) - timedelta(hours=3)
            db.add(stale_paused)
            await db.flush()

            result = await detect_stale_tasks(db, threshold_minutes=60)
            assert "tsk_stale_paused_001" in result["stale_task_ids"]
            # P11-B125: PAUSED tasks are NOT reassigned (active pause ≠ abandonment)
            assert "tsk_stale_paused_001" not in result["reassigned_task_ids"]
            assert "tsk_stale_paused_001" not in result["cancelled_task_ids"]

            await db.rollback()

    @pytest.mark.asyncio
    async def test_no_stale_tasks_when_all_fresh(self):
        """所有任务都是最近的 → 不检测到 stale。"""
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-stale-fresh"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-stale-fresh"))
            await db.flush()

            task = Task(
                id="tsk_active_001",
                project_id=project_id,
                title="Active Task",
                description="Being worked on",
                status=TaskStatus.IN_PROGRESS,
                owner_type="worker",
                owner_id="ag_active_001",
            )
            task.claimed_at = datetime.now(timezone.utc)
            task.updated_at = datetime.now(timezone.utc)
            db.add(task)
            await db.flush()

            result = await detect_stale_tasks(db, threshold_minutes=60)
            assert result["stale_count"] == 0
            assert result["stale_task_ids"] == []
            assert result["cancelled_count"] == 0
            assert result["cancelled_task_ids"] == []

            await db.rollback()

    # ── P11-B108: auto-cancel gate ──

    @pytest.mark.asyncio
    async def test_auto_cancel_after_max_detections(self):
        """反无限 stale 门禁：≥10 次 stale 检测 → 自动取消。"""
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-autocancel"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-autocancel"))
            await db.flush()

            task = Task(
                id="tsk_autocancel_001",
                project_id=project_id,
                title="Auto-cancel Task",
                description="Should be cancelled after max detections",
                status=TaskStatus.IN_PROGRESS,
                owner_type="worker",
                owner_id="ag_autocancel_001",
            )
            task.claimed_at = datetime.now(timezone.utc) - timedelta(hours=5)
            task.updated_at = datetime.now(timezone.utc) - timedelta(hours=5)
            db.add(task)
            await db.flush()

            # Simulate 10 prior stale detections (max_detections default = 10)
            for i in range(10):
                await event_store.record(
                    db,
                    event_type="task.stale_detected",
                    team_id=team_id,
                    actor_type=ActorType.SYSTEM,
                    actor_id="stale_task_detector",
                    target_type="task",
                    target_id=task.id,
                    payload={"task_id": task.id, "detection_count": i + 1, "max_detections": 10},
                )
            await db.flush()

            result = await detect_stale_tasks(db, threshold_minutes=60)
            # Should be CANCELLED, not just detected
            assert result["stale_count"] == 0
            assert result["cancelled_count"] == 1
            assert "tsk_autocancel_001" in result["cancelled_task_ids"]

            await db.flush()
            await db.refresh(task)
            assert task.status == TaskStatus.CANCELLED

            await db.rollback()

    # ── P11-B88 detect_stale_verifications tests ──

    @pytest.mark.asyncio
    async def test_detect_stale_verifications_basic(self):
        """扫描过期 in_verification 任务 → 自动回退到 in_progress。"""
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj"))
            await db.flush()

            # Stale in_verification task (>30 min without update)
            stale = Task(
                id="tsk_stale_verif_001",
                project_id=project_id,
                title="Stale Verification",
                description="Waiting for verification too long",
                status=TaskStatus.IN_VERIFICATION,
                owner_type="worker",
                owner_id="ag_stale_001",
            )
            stale.updated_at = datetime.now(timezone.utc) - timedelta(minutes=45)
            db.add(stale)

            # Fresh in_verification task
            fresh = Task(
                id="tsk_fresh_verif_001",
                project_id=project_id,
                title="Fresh Verification",
                description="Just submitted",
                status=TaskStatus.IN_VERIFICATION,
                owner_type="worker",
                owner_id="ag_fresh_001",
            )
            fresh.updated_at = datetime.now(timezone.utc)
            db.add(fresh)
            await db.flush()

            result = await detect_stale_verifications(db, threshold_minutes=30)
            assert result["reverted_count"] == 1
            assert "tsk_stale_verif_001" in result["reverted_task_ids"]
            assert "tsk_fresh_verif_001" not in result["reverted_task_ids"]
            assert result["cancelled_count"] == 0

            # Flush to persist status changes before reloading from DB
            await db.flush()
            await db.refresh(stale)
            assert stale.status == TaskStatus.IN_PROGRESS
            # Fresh task unaffected
            await db.refresh(fresh)
            assert fresh.status == TaskStatus.IN_VERIFICATION

            await db.rollback()

    @pytest.mark.asyncio
    async def test_detect_stale_verifications_ping_pong_gate(self):
        """反 ping-pong 门禁：≥5 次 auto-revert → auto-cancel。"""
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-gate"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-gate"))
            await db.flush()

            task = Task(
                id="tsk_pingpong_001",
                project_id=project_id,
                title="Ping Pong Task",
                description="Keeps getting reverted",
                status=TaskStatus.IN_VERIFICATION,
                owner_type="worker",
                owner_id="ag_pingpong_001",
            )
            task.updated_at = datetime.now(timezone.utc) - timedelta(minutes=45)
            db.add(task)
            await db.flush()

            # Simulate 5 prior auto-reverts (pre-existing events)
            # B22: verification_max_auto_reverts=5 → need ≥5 prior reverts to trigger cancel
            for i in range(5):
                await event_store.record(
                    db,
                    event_type="task.verification_timeout_reverted",
                    team_id=team_id,
                    actor_type=ActorType.SYSTEM,
                    actor_id="verification_timeout_detector",
                    target_type="task",
                    target_id=task.id,
                    payload={"task_id": task.id, "auto_revert_count": i + 1},
                )
            await db.flush()

            result = await detect_stale_verifications(db, threshold_minutes=30)
            # Should be CANCELLED, not reverted (ping-pong gate)
            assert result["reverted_count"] == 0
            assert result["cancelled_count"] == 1
            assert "tsk_pingpong_001" in result["cancelled_task_ids"]

            await db.flush()
            await db.refresh(task)
            assert task.status == TaskStatus.CANCELLED

            await db.rollback()

    # ── P12-B25 (PFL-128): READY task 无人认领检测 ──

    @pytest.mark.asyncio
    async def test_detect_unclaimed_ready_tasks(self):
        """READY task 超过阈值无人认领 → 检测到并记录事件。"""
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-ready-unclaimed"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-ready"))
            await db.flush()

            # READY task 60 分钟未更新 — 远超 30min 阈值
            task = Task(
                id="tsk_ready_unclaimed_001",
                project_id=project_id,
                title="Unclaimed READY Task",
                description="Sitting ready for too long",
                status=TaskStatus.READY,
                required_capabilities='["code-generation"]',
            )
            task.updated_at = datetime.now(timezone.utc) - timedelta(minutes=60)
            db.add(task)
            await db.flush()

            result = await detect_unclaimed_ready_tasks(db, threshold_minutes=30)
            assert result["unclaimed_count"] == 1
            assert "tsk_ready_unclaimed_001" in result["unclaimed_task_ids"]

            # 验证事件已记录
            events_result = await db.execute(
                select(Event).where(
                    Event.event_type == "task.ready_unclaimed",
                    Event.target_id == "tsk_ready_unclaimed_001",
                )
            )
            events = events_result.scalars().all()
            assert len(events) == 1
            payload = json.loads(events[0].payload)
            assert payload["required_capabilities"] == '["code-generation"]'
            assert payload["unclaimed_minutes"] >= 59

            await db.rollback()

    @pytest.mark.asyncio
    async def test_no_unclaimed_when_ready_is_fresh(self):
        """Fresh READY task → 不误报。"""
        async with async_session_factory() as db:
            team_id = generate_id("team")
            project_id = generate_id("project")
            db.add(Team(id=team_id, name="Test", slug="test-ready-fresh"))
            db.add(Project(id=project_id, team_id=team_id, name="Test Project", slug="test-proj-fresh"))
            await db.flush()

            # Fresh READY task
            task = Task(
                id="tsk_ready_fresh_001",
                project_id=project_id,
                title="Fresh READY Task",
                description="Just became ready",
                status=TaskStatus.READY,
            )
            db.add(task)
            await db.flush()

            result = await detect_unclaimed_ready_tasks(db, threshold_minutes=30)
            assert result["unclaimed_count"] == 0
            assert len(result["unclaimed_task_ids"]) == 0

            await db.rollback()
