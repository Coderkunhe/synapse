"""P5-B15 — TaskContinuityDetector 单元测试。

测试策略:
- 通过 async_session_factory 直接访问 DB（与 conftest.py 模式相同）
- 每个测试播种自己的数据，try/finally 关闭以避免跨测试污染
- 覆盖: 首次检查、已禁用、间隔守卫、未完成检测、
  快照持久化+检索、摘要生成（进行中/已解决）、
  边界情况（空数据、仅终态任务）
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

# ── 在任何项目导入之前设置测试 DB URL ────────────────────
import os
import tempfile
from pathlib import Path

_test_dir = Path(tempfile.gettempdir()) / "synapse_continuity_tests"
_test_dir.mkdir(exist_ok=True)
_test_db_fd, _TEST_DB_PATH = tempfile.mkstemp(
    suffix=".db", prefix="test_continuity_", dir=str(_test_dir)
)
os.close(_test_db_fd)

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ["DEBUG"] = "false"

from src.config import ContinuityConfig, Settings  # noqa: E402
from src.continuity.detector import (  # noqa: E402
    ContinuityResult,
    ContinuitySummary,
    TaskContinuityDetector,
)
from src.db import async_session_factory, engine  # noqa: E402
from src.models.base import Base  # noqa: E402
from src.utils.id_gen import generate_id  # noqa: E402


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """所有测试完成后清理临时数据库。"""
    try:
        Path(_TEST_DB_PATH).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def _create_tables():
    """为整个会话创建所有表。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# ── 辅助函数 ────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_project(project_id: str, team_id: str):
    """插入最小化的 project 行以使 FK 约束通过。"""
    now_ts = _now().strftime("%Y-%m-%d %H:%M:%S")
    async with async_session_factory() as db:
        await db.execute(
            text(
                "INSERT INTO team (id, name, slug, created_at, updated_at) "
                "VALUES (:id, :name, :slug, :ca, :ua)"
            ),
            {"id": team_id, "name": "Test Team", "slug": f"test-{team_id[-8:]}",
             "ca": now_ts, "ua": now_ts},
        )
        await db.execute(
            text(
                "INSERT INTO project (id, team_id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, :tid, :name, :slug, :status, :ca, :ua)"
            ),
            {"id": project_id, "tid": team_id, "name": "Test Project",
             "slug": f"proj-{project_id[-8:]}", "status": "active",
             "ca": now_ts, "ua": now_ts},
        )
        await db.commit()


async def _seed_task(
    task_id: str,
    project_id: str,
    *,
    title: str = "Test Task",
    status: str = "backlog",
    priority: str = "p2",
    owner_type: str | None = None,
    owner_id: str | None = None,
    created_at: datetime | None = None,
):
    """插入单个任务行。"""
    async with async_session_factory() as db:
        ts = (created_at or _now()).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            text(
                "INSERT INTO task (id, project_id, title, status, priority, "
                "owner_type, owner_id, version_no, redo_count, created_at, updated_at) "
                "VALUES (:id, :pid, :title, :status, :priority, "
                ":ot, :oid, :ver, 0, :ca, :ua)"
            ),
            {
                "id": task_id,
                "pid": project_id,
                "title": title,
                "status": status,
                "priority": priority,
                "ot": owner_type,
                "oid": owner_id,
                "ver": 1,
                "ca": ts,
                "ua": ts,
            },
        )
        await db.commit()


async def _seed_event(
    event_id: str,
    team_id: str,
    *,
    event_type: str = "task.created",
    actor_type: str = "human",
    actor_id: str = "mem_0000000000000001",
    target_type: str = "task",
    target_id: str = "tsk_0000000000000001",
    payload: str = "{}",
    created_at: datetime | None = None,
):
    """插入单个事件行。"""
    async with async_session_factory() as db:
        ts = (created_at or _now()).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            text(
                "INSERT INTO event (id, team_id, event_type, actor_type, "
                "actor_id, target_type, target_id, payload, created_at) "
                "VALUES (:id, :tid, :et, :at, :ai, :tt, :ti, :p, :ca)"
            ),
            {
                "id": event_id,
                "tid": team_id,
                "et": event_type,
                "at": actor_type,
                "ai": actor_id,
                "tt": target_type,
                "ti": target_id,
                "p": payload,
                "ca": ts,
            },
        )
        await db.commit()


# ═══════════════════════════════════════════════════════════════════
# 首次检查 / 已禁用 / 间隔守卫
# ═══════════════════════════════════════════════════════════════════


class TestDetectFirstCheck:
    """空项目 → 首次检查结果。"""

    @pytest.mark.asyncio
    async def test_empty_project_is_first_check(self, _create_tables):
        """无事件、无任务、无快照 → is_first_check=True。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is not None
            assert result.is_first_check is True
            assert result.last_activity_at is None
            assert result.last_activity_type is None
            assert result.unfinished_tasks == []

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, _create_tables):
        """功能开关关闭 → detect() 返回 None。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=False))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is None


class TestSnapshotGap:
    """快照间隔守卫 — 防止同一会话内过度检测。"""

    @pytest.mark.asyncio
    async def test_within_gap_returns_none(self, _create_tables):
        """间隔内的近期快照 → detect() 返回 None。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        # 创建一个非常近期的快照（刚刚）
        cfg = Settings(
            continuity=ContinuityConfig(
                enabled=True,
                snapshot_gap_seconds=1800,
            ),
        )
        detector = TaskContinuityDetector(cfg)

        # 首先保存一个快照
        result = ContinuityResult(
            last_activity_at=_now(),
            last_activity_type="task.created",
            unfinished_tasks=[],
            is_first_check=True,
        )
        async with async_session_factory() as db:
            await detector.save_snapshot(db, result, pid)
            await db.commit()

        # 现在检测 — 应在间隔内
        async with async_session_factory() as db:
            result2 = await detector.detect(db, pid)
            assert result2 is None

    @pytest.mark.asyncio
    async def test_old_snapshot_allows_detection(self, _create_tables):
        """快照超过间隔时间 → 允许检测。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(
            continuity=ContinuityConfig(
                enabled=True,
                snapshot_gap_seconds=600,  # 10 分钟间隔
            ),
        )
        detector = TaskContinuityDetector(cfg)

        # 直接插入一个旧快照（40 分钟前 — 远超间隔）
        old_ts = (_now() - timedelta(seconds=2400)).strftime("%Y-%m-%d %H:%M:%S")
        async with async_session_factory() as db:
            await db.execute(
                text(
                    "INSERT INTO continuity_snapshot (id, project_id, "
                    "last_activity_at, unfinished_tasks_json, created_at, updated_at) "
                    "VALUES (:id, :pid, :la, :ut, :ca, :ua)"
                ),
                {
                    "id": generate_id("continuity_snapshot"),
                    "pid": pid,
                    "la": None,
                    "ut": "[]",
                    "ca": old_ts,
                    "ua": old_ts,
                },
            )
            await db.commit()

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            # 旧快照 + gap=600s → 应允许检测
            assert result is not None
            assert result.is_first_check is False  # 存在历史快照


# ═══════════════════════════════════════════════════════════════════
# 最近活动检测
# ═══════════════════════════════════════════════════════════════════


class TestDetectLastActivity:
    """Event 表是最近活动的唯一来源。"""

    @pytest.mark.asyncio
    async def test_finds_latest_event(self, _create_tables):
        """返回最近事件的时间戳 + 类型。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        # 创建真实任务以便事件可以 JOIN target_id
        task_id = generate_id("task")
        await _seed_task(task_id, pid, title="事件关联任务", status="in_progress")

        older = _now() - timedelta(hours=2)
        newer = _now() - timedelta(hours=1)

        await _seed_event(
            generate_id("event"), tid,
            event_type="task.created",
            target_id=task_id,
            created_at=older,
        )
        await _seed_event(
            generate_id("event"), tid,
            event_type="task.claimed",
            target_id=task_id,
            created_at=newer,
        )

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is not None
            assert result.last_activity_type == "task.claimed"

    @pytest.mark.asyncio
    async def test_no_events_is_first_check(self, _create_tables):
        """完全没有事件 → last_activity_at 为 None。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is not None
            assert result.last_activity_at is None
            assert result.last_activity_type is None
            assert result.is_first_check is True


# ═══════════════════════════════════════════════════════════════════
# 未完成任务检测
# ═══════════════════════════════════════════════════════════════════


class TestDetectUnfinishedTasks:
    """检测非终态任务；排除终态任务。"""

    @pytest.mark.asyncio
    async def test_detects_non_terminal_statuses(self, _create_tables):
        """backlog、ready、in_progress、in_verification → 全部检测到。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        for i, status in enumerate(["backlog", "ready", "in_progress", "in_verification"]):
            await _seed_task(
                generate_id("task"), pid,
                title=f"任务 {i}",
                status=status,
            )

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is not None
            assert len(result.unfinished_tasks) == 4
            statuses = {t["status"] for t in result.unfinished_tasks}
            assert statuses == {"backlog", "ready", "in_progress", "in_verification"}

    @pytest.mark.asyncio
    async def test_terminal_statuses_excluded(self, _create_tables):
        """completed + cancelled → 不检测。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        await _seed_task(generate_id("task"), pid, title="已完成", status="completed")
        await _seed_task(generate_id("task"), pid, title="已取消", status="cancelled")

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is not None
            assert result.unfinished_tasks == []

    @pytest.mark.asyncio
    async def test_mixed_statuses(self, _create_tables):
        """终态 + 非终态混合 → 仅返回非终态。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        await _seed_task(generate_id("task"), pid, title="进行中", status="in_progress")
        await _seed_task(generate_id("task"), pid, title="已完成", status="completed")

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is not None
            assert len(result.unfinished_tasks) == 1
            assert result.unfinished_tasks[0]["title"] == "进行中"

    @pytest.mark.asyncio
    async def test_includes_owner_info(self, _create_tables):
        """任务字典包含 owner_type + owner_id。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        await _seed_task(
            generate_id("task"), pid,
            title="已被认领",
            status="in_progress",
            owner_type="worker",
            owner_id="agt_testagent1234567",
        )

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        async with async_session_factory() as db:
            result = await detector.detect(db, pid)
            assert result is not None
            t = result.unfinished_tasks[0]
            assert t["owner_type"] == "worker"
            assert t["owner_id"] == "agt_testagent1234567"


# ═══════════════════════════════════════════════════════════════════
# 快照持久化
# ═══════════════════════════════════════════════════════════════════


class TestSaveSnapshot:
    """save_snapshot() 持久化并可检索。"""

    @pytest.mark.asyncio
    async def test_persists_and_retrieves(self, _create_tables):
        """快照保存 → get_recent_snapshots 可读回。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        result = ContinuityResult(
            last_activity_at=_now(),
            last_activity_type="task.created",
            unfinished_tasks=[
                {"id": "tsk_001", "title": "测试任务", "status": "in_progress",
                 "priority": "p1", "owner_type": None, "owner_id": None},
            ],
            is_first_check=True,
        )

        async with async_session_factory() as db:
            await detector.save_snapshot(db, result, pid)
            await db.commit()

        # 读回
        async with async_session_factory() as db:
            from src.models.continuity import ContinuitySnapshot as CS
            from sqlalchemy import select
            rows = (await db.execute(
                select(CS).where(CS.project_id == pid).order_by(CS.created_at.desc())
            )).scalars().all()
            assert len(rows) == 1
            assert rows[0].project_id == pid
            tasks = json.loads(str(rows[0].unfinished_tasks_json))
            assert len(tasks) == 1
            assert tasks[0]["id"] == "tsk_001"

    @pytest.mark.asyncio
    async def test_empty_unfinished_tasks(self, _create_tables):
        """无未完成任务的快照正确持久化。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        result = ContinuityResult(
            last_activity_at=_now(),
            last_activity_type="task.created",
            unfinished_tasks=[],
            is_first_check=False,
        )

        async with async_session_factory() as db:
            await detector.save_snapshot(db, result, pid)
            await db.commit()

        async with async_session_factory() as db:
            from src.models.continuity import ContinuitySnapshot as CS
            from sqlalchemy import select
            rows = (await db.execute(
                select(CS).where(CS.project_id == pid)
            )).scalars().all()
            assert len(rows) == 1
            assert json.loads(str(rows[0].unfinished_tasks_json)) == []

    @pytest.mark.asyncio
    async def test_multiple_snapshots_create_separate_rows(self, _create_tables):
        """多次保存 → 多行（不覆盖）。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        for i in range(3):
            async with async_session_factory() as db:
                result = ContinuityResult(
                    last_activity_at=_now() - timedelta(hours=i),
                    last_activity_type="task.created",
                    unfinished_tasks=[{"id": f"tsk_{i}", "title": f"任务 {i}",
                                       "status": "in_progress", "priority": "p2",
                                       "owner_type": None, "owner_id": None}],
                    is_first_check=(i == 0),
                )
                await detector.save_snapshot(db, result, pid)
                await db.commit()

        async with async_session_factory() as db:
            from src.models.continuity import ContinuitySnapshot as CS
            from sqlalchemy import select, func
            count = (await db.execute(
                select(func.count(CS.id)).where(CS.project_id == pid)
            )).scalar()
            assert count == 3


# ═══════════════════════════════════════════════════════════════════
# 摘要生成
# ═══════════════════════════════════════════════════════════════════


class TestGenerateSummary:
    """generate_summary() 对比当前状态与历史快照。"""

    @pytest.mark.asyncio
    async def test_no_history_yields_empty_summary(self, _create_tables):
        """无历史快照 → 空的 ongoing/resolved，干净的摘要文本。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        result = ContinuityResult(
            last_activity_at=_now(),
            last_activity_type="task.created",
            unfinished_tasks=[
                {"id": "tsk_001", "title": "测试", "status": "in_progress",
                 "priority": "p1", "owner_type": None, "owner_id": None},
            ],
            is_first_check=False,
        )

        async with async_session_factory() as db:
            summary = await detector.generate_summary(db, result, pid, num_snapshots=3)
            assert summary.previous_snapshots == []
            assert summary.ongoing_tasks == []
            assert summary.resolved_tasks == []
            assert "1 个未完成任务" in summary.summary_text

    @pytest.mark.asyncio
    async def test_first_check_summary(self, _create_tables):
        """is_first_check=True → 摘要提及首次检查。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        result = ContinuityResult(
            last_activity_at=None,
            last_activity_type=None,
            is_first_check=True,
        )

        async with async_session_factory() as db:
            summary = await detector.generate_summary(db, result, pid)
            assert "首次检查" in summary.summary_text

    @pytest.mark.asyncio
    async def test_ongoing_tasks_detected(self, _create_tables):
        """任务同时出现在当前 + 历史快照中 → 进行中。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        # 保存一个包含 2 个任务的快照
        async with async_session_factory() as db:
            r1 = ContinuityResult(
                last_activity_at=_now() - timedelta(hours=2),
                last_activity_type="task.created",
                unfinished_tasks=[
                    {"id": "tsk_a", "title": "持续任务", "status": "in_progress",
                     "priority": "p1", "owner_type": None, "owner_id": None},
                    {"id": "tsk_b", "title": "已完成任务", "status": "in_progress",
                     "priority": "p2", "owner_type": None, "owner_id": None},
                ],
                is_first_check=True,
            )
            await detector.save_snapshot(db, r1, pid)
            await db.commit()

        # 当前结果: tsk_a 仍未完成，tsk_b 已解决
        result = ContinuityResult(
            last_activity_at=_now(),
            last_activity_type="task.claimed",
            unfinished_tasks=[
                {"id": "tsk_a", "title": "持续任务", "status": "in_progress",
                 "priority": "p1", "owner_type": "worker", "owner_id": "agt_x"},
            ],
            is_first_check=False,
        )

        async with async_session_factory() as db:
            summary = await detector.generate_summary(db, result, pid, num_snapshots=3)
            assert len(summary.ongoing_tasks) == 1
            assert summary.ongoing_tasks[0]["id"] == "tsk_a"
            assert len(summary.resolved_tasks) == 1
            assert summary.resolved_tasks[0]["id"] == "tsk_b"
            assert "1 项持续未解决" in summary.summary_text
            assert "1 项已解决" in summary.summary_text

    @pytest.mark.asyncio
    async def test_empty_current_yields_clean_summary(self, _create_tables):
        """无未完成任务 → 干净的摘要文本。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        result = ContinuityResult(
            last_activity_at=_now(),
            last_activity_type="task.created",
            unfinished_tasks=[],
            is_first_check=False,
        )

        async with async_session_factory() as db:
            summary = await detector.generate_summary(db, result, pid, num_snapshots=3)
            assert "所有任务已完成" in summary.summary_text

    @pytest.mark.asyncio
    async def test_respects_num_snapshots(self, _create_tables):
        """num_snapshots 参数限制查询的历史快照数量。"""
        pid = generate_id("project")
        tid = generate_id("team")
        await _seed_project(pid, tid)

        cfg = Settings(continuity=ContinuityConfig(enabled=True))
        detector = TaskContinuityDetector(cfg)

        # 保存 3 个快照
        for i in range(3):
            async with async_session_factory() as db:
                r = ContinuityResult(
                    last_activity_at=_now() - timedelta(hours=i),
                    last_activity_type="task.created",
                    unfinished_tasks=[
                        {"id": f"tsk_{i}", "title": f"任务 {i}",
                         "status": "in_progress", "priority": "p2",
                         "owner_type": None, "owner_id": None},
                    ],
                    is_first_check=(i == 0),
                )
                await detector.save_snapshot(db, r, pid)
                await db.commit()

        result = ContinuityResult(
            last_activity_at=_now(),
            last_activity_type="task.created",
            unfinished_tasks=[],
            is_first_check=False,
        )

        async with async_session_factory() as db:
            summary = await detector.generate_summary(db, result, pid, num_snapshots=1)
            assert len(summary.previous_snapshots) == 1

        async with async_session_factory() as db:
            summary_all = await detector.generate_summary(db, result, pid, num_snapshots=3)
            assert len(summary_all.previous_snapshots) == 3


# ═══════════════════════════════════════════════════════════════════
# 数据类默认值
# ═══════════════════════════════════════════════════════════════════


class TestDataclassDefaults:
    """ContinuityResult + ContinuitySummary 默认值。"""

    def test_result_defaults(self):
        """字段有合理的默认值。"""
        r = ContinuityResult(
            last_activity_at=None,
            last_activity_type=None,
        )
        assert r.unfinished_tasks == []
        assert r.is_first_check is False

    def test_summary_defaults(self):
        """所有字段默认为空。"""
        s = ContinuitySummary()
        assert s.previous_snapshots == []
        assert s.ongoing_tasks == []
        assert s.resolved_tasks == []
        assert s.summary_text == ""

    def test_result_with_data(self):
        """自定义值正确存储。"""
        now = _now()
        r = ContinuityResult(
            last_activity_at=now,
            last_activity_type="task.created",
            unfinished_tasks=[{"id": "tsk_1"}],
            is_first_check=True,
        )
        assert r.last_activity_at == now
        assert r.last_activity_type == "task.created"
        assert len(r.unfinished_tasks) == 1
        assert r.is_first_check is True

    def test_summary_with_data(self):
        """自定义值正确存储。"""
        s = ContinuitySummary(
            previous_snapshots=[{"id": "cs_1"}],
            ongoing_tasks=[{"id": "tsk_a"}],
            resolved_tasks=[{"id": "tsk_b"}],
            summary_text="一切就绪。",
        )
        assert len(s.previous_snapshots) == 1
        assert len(s.ongoing_tasks) == 1
        assert len(s.resolved_tasks) == 1
        assert s.summary_text == "一切就绪。"
