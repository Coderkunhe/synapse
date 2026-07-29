"""P10-B36: DecisionAudit Service 测试 — record + list + get."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.constants import ActorType, DecisionType, RiskLevel
from src.db import async_session_factory
from src.exceptions import NotFoundError
from src.models.decision_audit import DecisionAudit
from src.models.project import Project
from src.models.worker import Worker
from src.services.decision_audit_service import (
    get_decision,
    list_decisions,
    record_decision,
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
        name="Audit Test Project",
        slug=f"audit-test-{generate_id('project')[-8:]}",
        team_id=seed.team_id,
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.fixture
async def test_worker(db_session, seed):
    """创建一个测试用的 Worker."""
    worker = Worker(
        id=generate_id("worker"),
        name="Audit Test Worker",
        team_id=seed.team_id,
        actor_type="agent",
        status="active",
        api_key_hash="",
    )
    db_session.add(worker)
    await db_session.commit()
    return worker.id


# ══ Record Decision ══


class TestRecordDecision:
    async def test_record_approve_decision(self, db_session, test_project, test_worker, actor_info):
        """记录审批决策."""
        audit = await record_decision(
            db_session,
            authorization_request_id=None,
            decision_type=DecisionType.APPROVE,
            actor_type=ActorType.HUMAN,
            actor_id=actor_info["actor_id"],
            project_id=test_project,
            worker_id=test_worker,
            risk_level=RiskLevel.LOW,
            reason="Approved after review",
            context={"request_type": "api_auth"},
            team_id=actor_info["team_id"],
        )
        await db_session.commit()

        assert audit.id.startswith("da_")
        assert audit.decision_type == DecisionType.APPROVE
        assert audit.actor_type == ActorType.HUMAN
        assert audit.project_id == test_project
        assert audit.worker_id == test_worker
        assert audit.risk_level == RiskLevel.LOW
        assert audit.reason == "Approved after review"

    async def test_record_deny_decision(self, db_session, test_project, test_worker, actor_info):
        """记录拒绝决策."""
        audit = await record_decision(
            db_session,
            authorization_request_id=None,
            decision_type=DecisionType.DENY,
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            project_id=test_project,
            worker_id=test_worker,
            risk_level=RiskLevel.MEDIUM,
            reason="Denied by system policy",
            team_id=None,
        )
        await db_session.commit()

        assert audit.decision_type == DecisionType.DENY
        assert audit.actor_type == ActorType.SYSTEM
        assert audit.authorization_request_id is None

    async def test_record_decision_records_event(self, db_session, test_project, test_worker, actor_info):
        """记录决策同时写入 EventStore."""
        audit = await record_decision(
            db_session,
            authorization_request_id=None,
            decision_type=DecisionType.EXPIRE,
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            project_id=test_project,
            worker_id=test_worker,
            risk_level=RiskLevel.LOW,
            reason="Expired",
            team_id=None,
        )
        await db_session.commit()

        from src.models.event import Event
        result = await db_session.execute(
            select(Event).where(
                Event.target_type == "decision_audit",
                Event.target_id == audit.id,
                Event.event_type == "decision_audit.recorded",
            )
        )
        events = result.scalars().all()
        assert len(events) == 1

    async def test_record_all_decision_types(self, db_session, test_project, test_worker, actor_info):
        """五种决策类型都能记录."""
        for dt in [
            DecisionType.APPROVE,
            DecisionType.DENY,
            DecisionType.EXPIRE,
            DecisionType.CANCEL,
            DecisionType.AUTO_GRANT,
        ]:
            audit = await record_decision(
                db_session,
                authorization_request_id=None,
                decision_type=dt,
                actor_type=ActorType.SYSTEM,
                actor_id="system",
                project_id=test_project,
                worker_id=test_worker,
                risk_level=RiskLevel.LOW,
                reason=f"Test {dt}",
                team_id=None,
            )
            assert audit.decision_type == dt

    async def test_record_with_context_json(self, db_session, test_project, test_worker, actor_info):
        """context 参数被序列化为 JSON."""
        audit = await record_decision(
            db_session,
            authorization_request_id=None,
            decision_type=DecisionType.AUTO_GRANT,
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            project_id=test_project,
            worker_id=test_worker,
            risk_level=RiskLevel.LOW,
            context={"breaker_state": "open", "risk_score": 0.85},
            team_id=None,
        )
        await db_session.commit()

        assert audit.context_json is not None
        assert "breaker_state" in audit.context_json
        assert "risk_score" in audit.context_json


# ══ Get Decision ══


class TestGetDecision:
    async def test_get_existing_decision(self, db_session, test_project, test_worker, actor_info):
        """获取存在的决策审计."""
        created = await record_decision(
            db_session,
            authorization_request_id=None,
            decision_type=DecisionType.APPROVE,
            actor_type=ActorType.HUMAN,
            actor_id=actor_info["actor_id"],
            project_id=test_project,
            worker_id=test_worker,
            team_id=actor_info["team_id"],
        )
        await db_session.commit()

        fetched = await get_decision(db_session, created.id)
        assert fetched.id == created.id
        assert fetched.decision_type == DecisionType.APPROVE

    async def test_get_nonexistent_decision(self, db_session):
        """获取不存在的决策抛 NotFoundError."""
        with pytest.raises(NotFoundError) as exc_info:
            await get_decision(db_session, "nonexistent")
        assert "DecisionAudit" in exc_info.value.message


# ══ List Decisions ══


class TestListDecisions:
    async def test_list_all_decisions(self, db_session, test_project, test_worker, actor_info):
        """按 project 列出所有决策."""
        for i in range(3):
            await record_decision(
                db_session,
                authorization_request_id=None,
                decision_type=DecisionType.APPROVE,
                actor_type=ActorType.HUMAN,
                actor_id=actor_info["actor_id"],
                project_id=test_project,
                worker_id=test_worker,
                team_id=actor_info["team_id"],
            )
        await db_session.commit()

        items, cursor, total = await list_decisions(db_session, project_id=test_project)
        assert len(items) == 3
        assert total == 3

    async def test_list_filter_by_project(self, db_session, test_project, test_worker, actor_info):
        """按 project_id 筛选."""
        await record_decision(
            db_session,
            authorization_request_id=None,
            decision_type=DecisionType.DENY,
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            project_id=test_project,
            worker_id=test_worker,
            team_id=None,
        )
        await db_session.commit()

        items, _, total = await list_decisions(db_session, project_id=test_project)
        assert total == 1

    async def test_list_filter_by_decision_type(self, db_session, test_project, test_worker, actor_info):
        """按 decision_type 筛选."""
        await record_decision(
            db_session, authorization_request_id=None,
            decision_type=DecisionType.EXPIRE,
            actor_type=ActorType.SYSTEM, actor_id="system",
            project_id=test_project, worker_id=test_worker, team_id=None,
        )
        await record_decision(
            db_session, authorization_request_id=None,
            decision_type=DecisionType.APPROVE,
            actor_type=ActorType.HUMAN, actor_id=actor_info["actor_id"],
            project_id=test_project, worker_id=test_worker, team_id=actor_info["team_id"],
        )
        await db_session.commit()

        items, _, total = await list_decisions(db_session, project_id=test_project, decision_type=DecisionType.EXPIRE)
        assert total == 1
        assert items[0].decision_type == DecisionType.EXPIRE

    async def test_list_pagination(self, db_session, test_project, test_worker, actor_info):
        """游标分页."""
        for i in range(3):
            await record_decision(
                db_session, authorization_request_id=None,
                decision_type=DecisionType.CANCEL,
                actor_type=ActorType.SYSTEM, actor_id="system",
                project_id=test_project, worker_id=test_worker, team_id=None,
            )
        await db_session.commit()

        items, cursor, total = await list_decisions(db_session, project_id=test_project, limit=2)
        assert len(items) == 2
        assert total == 3
        assert cursor is not None

    async def test_list_filter_by_risk_level(self, db_session, test_project, test_worker, actor_info):
        """按 risk_level 筛选."""
        await record_decision(
            db_session, authorization_request_id=None,
            decision_type=DecisionType.APPROVE,
            actor_type=ActorType.HUMAN, actor_id=actor_info["actor_id"],
            project_id=test_project, worker_id=test_worker,
            risk_level=RiskLevel.HIGH, team_id=actor_info["team_id"],
        )
        await db_session.commit()

        items, _, total = await list_decisions(db_session, risk_level=RiskLevel.HIGH)
        assert total >= 1
        assert all(r.risk_level == RiskLevel.HIGH for r in items)
