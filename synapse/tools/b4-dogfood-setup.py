#!/usr/bin/env python3
"""P14-B4 狗粮环境搭建：注册 O + B1 + B2 Worker，创建 Project，生成 .env 文件。

Usage: cd synapse && SYNAPSE_DB_URL="sqlite+aiosqlite:///./data/synapse.db" python tools/b4-dogfood-setup.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.services.worker_service import register_worker
from src.services.project_service import create_project
from src.models.team import Team
from sqlalchemy import select

DB_URL = os.environ.get("SYNAPSE_DB_URL", "sqlite+aiosqlite:///./data/synapse.db")
TEAM_SLUG = "synapse-core"
PROJECT_NAME = "P14-B4 Dogfood"
PROJECT_SLUG = "p14-b4-dogfood"
PROJECT_DESC = "P14-B4 狗粮验证：depends_on 前端补齐功能 · 1O+2B 协作"
WORKTREES_DIR = Path(__file__).resolve().parent.parent.parent / ".claude" / "worktrees"

WORKERS = [
    {"name": "P14-B4 O", "provider": "claude", "provider_model": "sonnet", "role": "orchestrator"},
    {"name": "P14-B4 B1", "provider": "claude", "provider_model": "sonnet", "role": "builder"},
    {"name": "P14-B4 B2", "provider": "claude", "provider_model": "sonnet", "role": "builder"},
]


async def main():
    db_path = DB_URL.replace("sqlite+aiosqlite:///", "")
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), "..", db_path)
    print(f"DB: {db_path}")

    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # 1. Get team
        result = await db.execute(select(Team).where(Team.slug == TEAM_SLUG))
        team = result.scalar_one_or_none()
        if not team:
            print(f"❌ Team '{TEAM_SLUG}' not found")
            return 1
        print(f"✅ Team: {team.name} ({team.id})")

        # 2. Create project (skip if exists)
        from src.models.project import Project
        existing = await db.execute(
            select(Project).where(Project.team_id == team.id, Project.slug == PROJECT_SLUG)
        )
        project = existing.scalar_one_or_none()
        if project:
            print(f"⏭️  Project exists: {project.name} ({project.id})")
        else:
            project = await create_project(
                db,
                team_id=team.id,
                name=PROJECT_NAME,
                slug=PROJECT_SLUG,
                description=PROJECT_DESC,
                default_branch=None,
                git_repo_url=None,
                api_docs_url=None,
                frontend_test_url=None,
                webhook_url=None,
                use_phase_mode=True,
                current_phase="P14",
                organization=None,
                metadata={"phase": "P14", "batch": "B4"},
                is_protected=False,
                actor_type="system",
                actor_id="system",
            )
            await db.commit()
            print(f"✅ Project: {project.name} ({project.id})")

        # 3. Register workers (skip if name exists)
        from src.models.worker import Worker
        results = []
        for w in WORKERS:
            existing_w = await db.execute(
                select(Worker).where(Worker.name == w["name"], Worker.team_id == team.id)
            )
            worker = existing_w.scalar_one_or_none()
            if worker:
                print(f"⏭️  Worker exists: {w['name']} ({worker.id})")
                results.append({"worker": worker, "api_key": "ALREADY_REGISTERED"})
            else:
                worker_obj, api_key = await register_worker(
                    db,
                    team_id=team.id,
                    name=w["name"],
                    provider=w["provider"],
                    provider_model=w["provider_model"],
                    system_prompt=None,
                    metadata={"worker_version": "0.0.0", "supported_events": []},
                    registered_by="system",
                    actor_type="agent",
                    actor_id="system",
                    batch_size=1,
                    project_id=project.id,
                    project_role=w["role"],
                )
                results.append({"worker": worker_obj, "api_key": api_key})
                print(f"✅ Worker: {w['name']} ({worker_obj.id}) · Key: {api_key}")

        await db.commit()

        # 4. Generate .env files
        print()
        for r in results:
            w = r["worker"]
            name = w.name
            api_key = r["api_key"]

            if "B1" in name:
                wt_synapse = WORKTREES_DIR / "p14-b4-b1" / "synapse"
            elif "B2" in name:
                wt_synapse = WORKTREES_DIR / "p14-b4-b2" / "synapse"
            elif "O" in name:
                wt_synapse = WORKTREES_DIR / "p14-b4-b1" / "synapse"
            else:
                continue

            if api_key == "ALREADY_REGISTERED":
                print(f"⚠️  {name}: 已存在，需手动获取 API key")
                continue

            wt_synapse.mkdir(parents=True, exist_ok=True)
            env_path = wt_synapse / ".env"
            env_content = (
                f"# Synapse Worker — {name}\n"
                f"SYNAPSE_API_KEY={api_key}\n"
                f"SYNAPSE_BASE_URL=http://localhost:8001\n"
                f"SYNAPSE_PROJECT_ID={project.id}\n"
                f"SYNAPSE_TEAM_ID={team.id}\n"
                f"SYNAPSE_WORKER_ID={w.id}\n"
            )
            env_path.write_text(env_content)
            print(f"✅ .env → {env_path}")

    # 5. Summary
    print()
    print("=" * 60)
    print("🏁 B4 狗粮环境就绪")
    print("=" * 60)
    print(f"   Team:    {team.name} ({team.id})")
    print(f"   Project: {project.name} ({project.id})")
    for r in results:
        w = r["worker"]
        print(f"   Worker:  {w.name:16s} {w.id}  key={r['api_key'][:20]}...")
    print()
    print("📁 Worktrees:")
    print(f"   B1 (backend):  {WORKTREES_DIR}/p14-b4-b1")
    print(f"   B2 (frontend): {WORKTREES_DIR}/p14-b4-b2")
    print()
    print("🚀 下一步: God's-eye 创建 Task → O 拆解 → B1/B2 实现 → O 验收")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
