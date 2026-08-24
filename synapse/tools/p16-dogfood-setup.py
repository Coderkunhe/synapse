#!/usr/bin/env python3
"""P16-B4 狗粮环境搭建：注册 O + Builder B1 + Builder B2，创建 Project，生成 .env + skill。

改自 p15-dogfood-setup.py。P16 差异：
  - Worker: P16-B4 O / B1 / B2（三者一次性注册 —— headless 执行环，非串行注册）
  - Project: P16-B4 Dogfood · phase P16 · batch B4 · slug p16-b4-dogfood
  - 需求: 内部功能「Worker 心跳健康度观测」（后端端点 + CLI 工具 · depends_on 链）
  - Worker cwd = worktree 根（O 为普通目录，B1/B2 为 git worktree）

Usage:
  cd synapse && .venv/bin/python tools/p16-dogfood-setup.py
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
PROJECT_NAME = "P16-B4 Dogfood"
PROJECT_SLUG = "p16-b4-dogfood"
PROJECT_DESC = "P16-B4 机制级修自主性验证：1O+2B headless 执行环零 human turn · 内部功能 Worker 心跳健康度观测"

# 仓库根 = synapse/ 的上一级
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKTREES_DIR = REPO_ROOT / ".claude" / "worktrees"

# 串行注册（headless 执行环 · depends_on 保证 A 先落地）：
#   O + B1 先注册（B1 worktree 先建）；B2 在 B1 交付 commit 后再注册（B2 worktree 后建，
#   checkout 同一分支 p16/b4-dogfood，从而拿到 B1 的代码）。O 为普通目录（不写代码）。
# 用 P16_SETUP_WORKERS 环境变量控制本轮注册哪些（逗号分隔 o,b1,b2），默认 o,b1。
_which = os.environ.get("P16_SETUP_WORKERS", "o,b1").split(",")
_ALL = {
    "o":  {"name": "P16-B4 O", "provider": "claude", "provider_model": "sonnet", "role": "orchestrator",
           "dir": WORKTREES_DIR / "p16-b4-o"},
    "b1": {"name": "P16-B4 B1", "provider": "claude", "provider_model": "sonnet", "role": "builder",
           "dir": WORKTREES_DIR / "p16-b4-b1"},
    "b2": {"name": "P16-B4 B2", "provider": "claude", "provider_model": "sonnet", "role": "builder",
           "dir": WORKTREES_DIR / "p16-b4-b2"},
}
WORKERS = [_ALL[k] for k in _which if k in _ALL]


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
                use_phase_mode=True, current_phase="P16", organization=None,
                metadata={"phase": "P16", "batch": "B4"},
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
    print("🏁 P16-B4 狗粮环境就绪（O + B1 + B2 · headless）")
    print("=" * 60)
    print(f"   Team:    {team.name} ({team.id})")
    print(f"   Project: {project.name} ({project.id})")
    print(f"   API URL: {API_URL}")
    print()
    print("   下一步起 headless worker（各一条命令 · 零 human turn）：")
    print(f"     O:  bash tools/start-worker.sh --project-dir {WORKTREES_DIR}/p16-b4-o")
    print(f"     B1: bash tools/start-worker.sh --project-dir {WORKTREES_DIR}/p16-b4-b1")
    print(f"     B2: bash tools/start-worker.sh --project-dir {WORKTREES_DIR}/p16-b4-b2")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
