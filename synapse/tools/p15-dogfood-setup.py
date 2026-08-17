#!/usr/bin/env python3
"""P15-B1 狗粮环境搭建：注册 O + Builder A Worker，创建 Project，生成 .env + skill。

改自 b4-dogfood-setup.py（P14-B5 已验证）。P15 差异：
  - Worker: P15-B1 O / A（Builder B 到 B2 再注册，depends_on 串行）
  - Project: P15-B1 Snippet Vault · phase P15 · batch B1
  - API URL: http://localhost:8000（b4 硬编码 8001 是 P14 临时值）
  - Worker cwd = worktree 根（snippet-vault/ 与 synapse/ 平级），非 synapse/ 子目录

Usage:
  cd synapse && .venv/bin/python tools/p15-dogfood-setup.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.services.worker_service import register_worker
from src.services.project_service import create_project
from src.models.team import Team

DB_URL = os.environ.get("SYNAPSE_DB_URL", "sqlite+aiosqlite:///./data/synapse.db")
API_URL = "http://localhost:8000"
TEAM_SLUG = "synapse-core"
PROJECT_NAME = "P15-B1 Snippet Vault"
PROJECT_SLUG = "p15-b1-snippet-vault"
PROJECT_DESC = "P15-B1 战略验证：独立外部功能 Snippet Vault · 1O+2B 协作 · 后端 → 前端 depends_on"

# 仓库根 = synapse/ 的上一级（snippet-vault/ 与 synapse/ 平级处）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKTREES_DIR = REPO_ROOT / ".claude" / "worktrees"

# B1 只注册 O + A；Builder B 到 B2 由 O 通过 API 或二次脚本注册
WORKERS = [
    {"name": "P15-B1 O", "provider": "claude", "provider_model": "sonnet", "role": "orchestrator",
     "dir": WORKTREES_DIR / "p15-o"},
    {"name": "P15-B1 A", "provider": "claude", "provider_model": "sonnet", "role": "builder",
     "dir": WORKTREES_DIR / "p15-a"},
]


async def main():
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # 1. Team
        result = await db.execute(select(Team).where(Team.slug == TEAM_SLUG))
        team = result.scalar_one_or_none()
        if not team:
            print(f"❌ Team '{TEAM_SLUG}' not found")
            return 1
        print(f"✅ Team: {team.name} ({team.id})")

        # 2. Project
        from src.models.project import Project
        existing = await db.execute(
            select(Project).where(Project.team_id == team.id, Project.slug == PROJECT_SLUG)
        )
        project = existing.scalar_one_or_none()
        if project:
            print(f"⏭️  Project exists: {project.name} ({project.id})")
        else:
            project = await create_project(
                db, team_id=team.id, name=PROJECT_NAME, slug=PROJECT_SLUG,
                description=PROJECT_DESC, default_branch=None, git_repo_url=None,
                api_docs_url=None, frontend_test_url=None, webhook_url=None,
                use_phase_mode=True, current_phase="P15", organization=None,
                metadata={"phase": "P15", "batch": "B1"},
                is_protected=False, actor_type="system", actor_id="system",
            )
            await db.commit()
            print(f"✅ Project: {project.name} ({project.id})")

        # 3. Register workers
        from src.models.worker import Worker
        results = []
        for w in WORKERS:
            existing_w = await db.execute(
                select(Worker).where(Worker.name == w["name"], Worker.team_id == team.id)
            )
            worker = existing_w.scalar_one_or_none()
            if worker:
                print(f"⏭️  Worker exists: {w['name']} ({worker.id})")
                results.append({"worker": worker, "api_key": "ALREADY_REGISTERED", "role": w["role"], "dir": w["dir"]})
            else:
                worker_obj, api_key = await register_worker(
                    db, team_id=team.id, name=w["name"], provider=w["provider"],
                    provider_model=w["provider_model"], system_prompt=None,
                    metadata={"worker_version": "0.0.0", "supported_events": []},
                    registered_by="system", actor_type="agent", actor_id="system",
                    batch_size=1, project_id=project.id, project_role=w["role"],
                )
                results.append({"worker": worker_obj, "api_key": api_key, "role": w["role"], "dir": w["dir"]})
                print(f"✅ Worker: {w['name']} ({worker_obj.id}) · Key: {api_key}")
        await db.commit()

        # 4. Generate .env + skill（worker cwd = worktree 根，.env 在 <dir>/.claude/.env）
        print()
        gen_script = Path(__file__).resolve().parent / "generate-skill.sh"
        for r in results:
            w = r["worker"]; name = w.name; api_key = r["api_key"]; role = r["role"]; wdir = r["dir"]
            if api_key == "ALREADY_REGISTERED":
                print(f"⚠️  {name}: 已存在，需手动获取 API key，跳过 .env")
                continue

            claude_dir = wdir / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            env_path = claude_dir / ".env"
            env_path.write_text(
                f"# Synapse Worker — {name}\n"
                f"SYNAPSE_API_KEY={api_key}\n"
                f"SYNAPSE_API_URL={API_URL}\n"
                f"SYNAPSE_PROJECT_ID={project.id}\n"
                f"SYNAPSE_TEAM_ID={team.id}\n"
                f"SYNAPSE_WORKER_ID={w.id}\n"
                f"SYNAPSE_WORKER_ROLE={role}\n"
            )
            print(f"✅ .env → {env_path}")

            if gen_script.exists():
                import subprocess
                result = subprocess.run(
                    ["bash", str(gen_script), "--from-api",
                     "--output", str(wdir),
                     "--api-url", API_URL,
                     "--worker-id", w.id,
                     "--project-id", project.id,
                     "--role", role,
                     "--api-key", api_key],
                    capture_output=True, text=True,
                )
                print(f"✅ generate-skill.sh → {wdir}" if result.returncode == 0
                      else f"⚠️  generate-skill.sh failed: {result.stderr[:300]}")
            else:
                print(f"⚠️  generate-skill.sh not found at {gen_script}")

    print()
    print("=" * 60)
    print("🏁 P15-B1 狗粮环境就绪（O + Builder A）")
    print("=" * 60)
    print(f"   Team:    {team.name} ({team.id})")
    print(f"   Project: {project.name} ({project.id})")
    print(f"   API URL: {API_URL}")
    print()
    print("   下一步开窗口：")
    print(f"     O 窗口:  cd {WORKTREES_DIR}/p15-o && claude")
    print(f"     A 窗口:  cd {WORKTREES_DIR}/p15-a && claude")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
