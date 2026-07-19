"""P10-B36: ProtectionReport Service 测试 — CRUD + run_report skeleton."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.constants import ActorType, ProtectionReportType, ProtectionReportStatus
from src.db import async_session_factory
from src.exceptions import NotFoundError
from src.models.protection_report import ProtectionReport
from src.models.project import Project
from src.services.protection_service import (
    create_report,
    get_report,
    list_reports,
    run_report,
)
from src.utils.id_gen import generate_id


# ══ Fixtures ══


@pytest_asyncio.fixture
async def db_session():
    """每个测试一个独立数据库会话，测试结束回滚."""
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def actor_info(seed):
    return {
        "team_id": seed.team_id,
        "actor_type": ActorType.WORKER,
        "actor_id": seed.worker_id,
    }


@pytest.fixture
async def test_project(db_session, seed):
    """创建一个测试用的 Project."""
    project = Project(
        id=generate_id("project"),
        name="Protection Test Project",
        slug=f"prot-test-{generate_id('project')[-8:]}",
        team_id=seed.team_id,
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


# ══ Create Report ══


class TestCreateReport:
    async def test_create_manual_report(self, db_session, test_project, actor_info):
        """创建手动触发的保护报告."""
        report = await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.CROSS_PROJECT_ACCESS,
            triggered_by="manual",
            parameters={"threshold": 0.7},
            **actor_info,
        )
        await db_session.commit()

        assert report.id.startswith("prpt_")
        assert report.project_id == test_project
        assert report.report_type == ProtectionReportType.CROSS_PROJECT_ACCESS
        assert report.status == ProtectionReportStatus.PENDING
        assert report.triggered_by == "manual"
        assert report.parameters_json is not None
        assert "threshold" in report.parameters_json

    async def test_create_scheduled_report(self, db_session, test_project, actor_info):
        """创建定时触发的保护报告."""
        report = await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.SENSITIVE_WORKER_OVERLAP,
            triggered_by="scheduled",
            **actor_info,
        )
        await db_session.commit()

        assert report.triggered_by == "scheduled"
        assert report.status == ProtectionReportStatus.PENDING
        assert report.parameters_json is None

    async def test_create_report_records_event(self, db_session, test_project, actor_info):
        """创建报告会记录 EventStore 事件."""
        report = await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.CAPABILITY_DRIFT,
            **actor_info,
        )
        await db_session.commit()

        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "protection_report",
                Event.target_id == report.id,
            )
        )
        events = result.scalars().all()
        assert len(events) >= 1
        assert any(e.event_type == "protection_report.created" for e in events)


# ══ Get Report ══


class TestGetReport:
    async def test_get_existing_report(self, db_session, test_project, actor_info):
        """获取存在的报告."""
        created = await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.CROSS_PROJECT_ACCESS,
            **actor_info,
        )
        await db_session.commit()

        fetched = await get_report(db_session, created.id)
        assert fetched.id == created.id
        assert fetched.project_id == test_project

    async def test_get_nonexistent_report(self, db_session):
        """获取不存在的报告抛 NotFoundError."""
        with pytest.raises(NotFoundError) as exc_info:
            await get_report(db_session, "nonexistent_id")
        assert "ProtectionReport" in exc_info.value.message


# ══ List Reports ══


class TestListReports:
    async def test_list_all_reports(self, db_session, test_project, actor_info):
        """按 project 列出所有报告."""
        for i in range(3):
            await create_report(
                db_session,
                project_id=test_project,
                report_type=ProtectionReportType.CROSS_PROJECT_ACCESS,
                **actor_info,
            )
        await db_session.commit()

        items, cursor, total = await list_reports(db_session, project_id=test_project)
        assert len(items) == 3
        assert total == 3
        assert cursor is None  # 不超 limit

    async def test_list_filter_by_project(self, db_session, test_project, actor_info):
        """按 project_id 筛选."""
        # 在 test_project 中创建报告
        await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.CROSS_PROJECT_ACCESS,
            **actor_info,
        )
        await db_session.commit()

        items, _, total = await list_reports(db_session, project_id=test_project)
        assert len(items) == 1
        assert total == 1

    async def test_list_filter_by_status(self, db_session, test_project, actor_info):
        """按 status 筛选."""
        await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.CAPABILITY_DRIFT,
            **actor_info,
        )
        await db_session.commit()

        items, _, total = await list_reports(db_session, status=ProtectionReportStatus.PENDING)
        assert len(items) >= 1
        assert all(r.status == ProtectionReportStatus.PENDING for r in items)

    async def test_list_pagination(self, db_session, test_project, actor_info):
        """游标分页."""
        reports = []
        for i in range(3):
            r = await create_report(
                db_session,
                project_id=test_project,
                report_type=ProtectionReportType.CROSS_PROJECT_ACCESS,
                **actor_info,
            )
            reports.append(r)
        await db_session.commit()

        items, cursor, total = await list_reports(db_session, project_id=test_project, limit=2)
        assert len(items) == 2
        assert total == 3
        assert cursor is not None

        # Page 2
        items2, cursor2, _ = await list_reports(db_session, project_id=test_project, cursor=cursor, limit=2)
        assert len(items2) == 1
        assert cursor2 is None


# ══ Run Report ══


class TestRunReport:
    async def test_run_report_pending_to_completed(self, db_session, test_project, actor_info):
        """执行报告状态转换: pending → running → completed."""
        report = await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.CROSS_PROJECT_ACCESS,
            **actor_info,
        )
        await db_session.commit()

        result = await run_report(
            db_session,
            report_id=report.id,
            **actor_info,
        )
        await db_session.commit()

        assert result.status == ProtectionReportStatus.COMPLETED
        assert result.started_at is not None
        assert result.completed_at is not None
        # 骨架检测返回空结果
        assert result.result_json is not None
        result_data = json.loads(result.result_json)
        assert "findings" in result_data
        assert result_data["total_findings"] == 0
        assert result_data["risk_score"] == 0.0

    async def test_run_report_records_completion_event(self, db_session, test_project, actor_info):
        """执行完成记录 protection_report.completed 事件."""
        report = await create_report(
            db_session,
            project_id=test_project,
            report_type=ProtectionReportType.SENSITIVE_WORKER_OVERLAP,
            **actor_info,
        )
        await db_session.commit()

        await run_report(db_session, report_id=report.id, **actor_info)
        await db_session.commit()

        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "protection_report",
                Event.target_id == report.id,
                Event.event_type == "protection_report.completed",
            )
        )
        events = result.scalars().all()
        assert len(events) == 1

    async def test_run_report_all_types(self, db_session, test_project, actor_info):
        """三种检测类型都可执行."""
        for report_type in [
            ProtectionReportType.CROSS_PROJECT_ACCESS,
            ProtectionReportType.SENSITIVE_WORKER_OVERLAP,
            ProtectionReportType.CAPABILITY_DRIFT,
        ]:
            report = await create_report(
                db_session,
                project_id=test_project,
                report_type=report_type,
                **actor_info,
            )
            await db_session.commit()

            result = await run_report(db_session, report_id=report.id, **actor_info)
            await db_session.commit()
            assert result.status == ProtectionReportStatus.COMPLETED
