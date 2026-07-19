#!/usr/bin/env python3
"""L5 E2E verification for B47-B50 DB foundation track.

Verifies the full creation chain:
  Team → Project → Batch → Task → Agent → Skill

And confirms create_user_id is propagated from actor_id (not "system").
Uses FastAPI TestClient — no real server needed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ── Set test DB before any src imports ──
_test_dir = Path(tempfile.gettempdir()) / "synapse_l5_verify"
_test_dir.mkdir(exist_ok=True)
_db_path = _test_dir / "l5_verify.db"
_db_path.unlink(missing_ok=True)

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path}"
os.environ["DEBUG"] = "false"

from httpx import ASGITransport, AsyncClient
from src.config import settings
from src.db import async_session_factory, engine
from src.main import create_app
from src.models.base import Base
from src.models.member import Member
from src.models.team import Team
from src.auth import create_access_token
from src.utils.id_gen import generate_id


async def main():
    # ── Create tables ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # ── Seed team + admin member ──
        team_id = generate_id("team")
        member_id = generate_id("member")
        short = team_id.replace("tea_", "")[-12:]

        async with async_session_factory() as session:
            team = Team(id=team_id, name=f"L5 Test {short}", slug=f"l5-{short}")
            member = Member(
                id=member_id, team_id=team_id,
                user_id=f"user-{member_id[:8]}",
                display_name="Admin", role="admin",
            )
            session.add_all([team, member])
            await session.commit()

        token = create_access_token(
            user_id=f"user-{member_id[:8]}",
            member_id=member_id, team_id=team_id, role="admin",
        )
        headers = {"Authorization": f"Bearer {token}"}

        actor_id = member_id  # The member performing all actions
        print(f"Team: {team_id}  Member: {member_id}")

        # ── 1. Create Project ──
        r = await client.post(f"/v1/teams/{team_id}/projects", json={
            "team_id": team_id, "name": "L5 Verify Project",
            "slug": f"l5-{short}", "description": "E2E test",
        }, headers=headers)
        assert r.is_success, f"Project create failed: {r.text}"
        project = r.json()
        project_id = project["id"]
        assert project.get("create_user_id") == actor_id, \
            f"Project create_user_id={project.get('create_user_id')}, expected={actor_id}"
        print(f"✅ Project {project_id} — create_user_id={project['create_user_id']}")

        # ── 2. Create Batch ──
        r = await client.post(f"/v1/projects/{project_id}/batches", json={
            "project_id": project_id, "name": "L5 Batch 1", "description": "E2E batch",
        }, headers=headers)
        assert r.is_success, f"Batch create failed: {r.text}"
        batch = r.json()
        batch_id = batch["id"]
        assert batch.get("create_user_id") == actor_id, \
            f"Batch create_user_id={batch.get('create_user_id')}, expected={actor_id}"
        print(f"✅ Batch {batch_id} — create_user_id={batch['create_user_id']}")

        # ── 3. Create Task ──
        r = await client.post(f"/v1/projects/{project_id}/tasks", json={
            "project_id": project_id, "title": "L5 Test Task",
            "description": "E2E task", "priority": "p2",
            "verifications": [{"type": "manual", "description": "Review manually"}],
        }, headers=headers)
        assert r.is_success, f"Task create failed: {r.text}"
        task = r.json()
        task_id = task["id"]
        assert task.get("create_user_id") == actor_id, \
            f"Task create_user_id={task.get('create_user_id')}, expected={actor_id}"
        print(f"✅ Task {task_id} — create_user_id={task['create_user_id']}")

        # ── 4. Create Skill ──
        r = await client.post(f"/v1/teams/{team_id}/skills", json={
            "team_id": team_id, "name": "L5 Test Skill",
            "template_md": "# Test Skill\nE2E test skill template.",
        }, headers=headers)
        assert r.is_success, f"Skill create failed: {r.text}"
        skill = r.json()
        skill_id = skill["id"]
        assert skill.get("create_user_id") == actor_id, \
            f"Skill create_user_id={skill.get('create_user_id')}, expected={actor_id}"
        print(f"✅ Skill {skill_id} — create_user_id={skill['create_user_id']}")

        # ── 5. Register Agent ──
        r = await client.post(f"/v1/teams/{team_id}/agents", json={
            "team_id": team_id, "name": "L5 Test Agent",
            "provider": "claude", "provider_model": "claude-sonnet-5",
        }, headers=headers)
        assert r.is_success, f"Agent create failed: {r.text}"
        agent_resp = r.json()
        agent = agent_resp["agent"]
        agent_id = agent["id"]
        assert agent.get("create_user_id") == actor_id, \
            f"Agent create_user_id={agent.get('create_user_id')}, expected={actor_id}"
        print(f"✅ Agent {agent_id} — create_user_id={agent['create_user_id']}")

        # ── 6. Create Analysis ──
        r = await client.post(f"/v1/projects/{project_id}/analyses", json={
            "project_id": project_id, "title": "L5 Analysis",
            "content": "E2E analysis content.",
            "analysis_type": "design",
        }, headers=headers)
        assert r.is_success, f"Analysis create failed: {r.text}"
        analysis = r.json()
        assert analysis.get("create_user_id") == actor_id, \
            f"Analysis create_user_id={analysis.get('create_user_id')}, expected={actor_id}"
        print(f"✅ Analysis {analysis['id']} — create_user_id={analysis['create_user_id']}")

        # ── Summary ──
        print()
        print("═" * 60)
        print("🎉 L5 E2E 全链路验证通过")
        print(f"   6 实体创建成功 — create_user_id 全部 = actor_id ({actor_id[:16]}…)")
        print("═" * 60)

    await engine.dispose()
    _db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
