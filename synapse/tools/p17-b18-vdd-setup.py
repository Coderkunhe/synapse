#!/usr/bin/env python3
"""P17-B18 VDD 修复环境搭建（PFL-277 根治）。

单 builder worker（headless · git worktree）+ 1 条 VDD task（修复 PFL-277 的 spec）。
走 VDD 循环：God's-eye 建 Task → Builder 修（在 worktree 改 src/ + 跑 pytest）→ O 验收。

与 P17-B17 dogfood 的差异：
  - B17 的 worker 不写代码（普通目录隔离即可）。
  - B18 的 worker 要改 src/ + 跑 pytest → 必须 git worktree（DG-1）+ 共享 .venv。

设计决策：
  - worktree 在 `.claude/worktrees/p17-b18-builder`（分支 p17-b18-builder · DG-5 命名）。
  - worker 名 `p17-b18-builder`（区别于 B17 残留 p17-b17-builder）。
  - .venv symlink 到主 repo 的 synapse/.venv（worktree 不含 gitignored .venv）。
  - VDD task 建为 ready（builder 起后走 claim→execute 正常执行环）。

幂等：worker 按 name 去重、task 按 (project_id, title) 去重、worktree 已存在则跳过。

Usage:
  cd synapse && .venv/bin/python tools/p17-b18-vdd-setup.py [--dry-run]
"""
import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.services.worker_service import register_worker
from src.models.team import Team
from src.models.project import Project
from src.models.worker import Worker
from src.models.task import Task
from src.services import task_service

DB_URL = os.environ.get("SYNAPSE_DB_URL", "sqlite+aiosqlite:///./data/synapse.db")
API_URL = "http://localhost:8000"
TEAM_SLUG = "synapse-core"
PROJECT_SLUG = "synapse"  # 复用 seed 项目
WORKER_NAME = "p17-b18-builder"
WORKER_ROLE = "builder"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # ai-synapse/
WORKER_DIR = REPO_ROOT / ".claude" / "worktrees" / "p17-b18-builder"
BRANCH = "p17-b18-builder"
SPEC_PATH = Path(__file__).resolve().parent.parent / "docs" / "plans" / "p17-b18-pfl277-vdd.md"

TASK_TITLE = "P17-B18 VDD：修复 PFL-277（count_unread_mentions NOT IN NULL）"


def create_worktree() -> None:
    if (WORKER_DIR / ".git").exists() or WORKER_DIR.exists():
        print(f"⏭️  Worktree exists: {WORKER_DIR}")
        return
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "add", str(WORKER_DIR), "-b", BRANCH],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"⚠️  git worktree add failed: {r.stderr[:300]}")
        return
    print(f"✅ Worktree: {WORKER_DIR}（branch {BRANCH}）")

    # 共享 .venv（worktree 不含 gitignored .venv → symlink 主 repo 的）
    src_venv = REPO_ROOT / "synapse" / ".venv"
    dst_venv = WORKER_DIR / "synapse" / ".venv"
    if src_venv.exists() and not dst_venv.exists():
        dst_venv.symlink_to(src_venv, target_is_directory=True)
        print(f"✅ .venv symlink → {dst_venv}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="P17-B18 VDD 环境搭建（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不 commit")
    args = parser.parse_args()

    if not args.dry_run:
        create_worktree()

    if not SPEC_PATH.exists():
        print(f"❌ VDD spec 不存在: {SPEC_PATH}")
        return 1
    spec_text = SPEC_PATH.read_text(encoding="utf-8")

    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        team = (await db.execute(select(Team).where(Team.slug == TEAM_SLUG))).scalar_one_or_none()
        if not team:
            print(f"❌ Team '{TEAM_SLUG}' not found")
            return 1
        print(f"✅ Team: {team.name} ({team.id})")

        project = (await db.execute(
            select(Project).where(Project.team_id == team.id, Project.slug == PROJECT_SLUG)
        )).scalar_one_or_none()
        if not project:
            print(f"❌ Project '{PROJECT_SLUG}' not found")
            return 1
        print(f"✅ Project: {project.name} ({project.id})")

        # Worker（幂等）
        worker = (await db.execute(
            select(Worker).where(Worker.name == WORKER_NAME, Worker.team_id == team.id)
        )).scalar_one_or_none()
        api_key = "ALREADY_REGISTERED"
        if worker:
            print(f"⏭️  Worker exists: {worker.name} ({worker.id})")
        elif args.dry_run:
            print(f"🔍 [dry-run] 将注册 Worker: {WORKER_NAME}")
        else:
            worker, api_key = await register_worker(
                db, team_id=team.id, name=WORKER_NAME, provider="claude",
                provider_model="sonnet", system_prompt=None,
                metadata={"worker_version": "0.0.0", "supported_events": []},
                registered_by="system", actor_type="agent", actor_id="system",
                batch_size=1, project_id=project.id, project_role=WORKER_ROLE,
            )
            await db.commit()
            print(f"✅ Worker: {worker.name} ({worker.id}) · Key: {api_key}")

        # VDD task（幂等 · ready 供 builder claim）
        task = (await db.execute(
            select(Task).where(Task.project_id == project.id, Task.title == TASK_TITLE)
        )).scalar_one_or_none()
        if task:
            print(f"⏭️  Task exists: {task.id} · status={task.status}")
        elif args.dry_run:
            print(f"🔍 [dry-run] 将创建 ready VDD task: {TASK_TITLE}")
        else:
            task = await task_service.create_task(
                db, project_id=project.id, title=TASK_TITLE, description=spec_text,
                priority="p1", parent_task_id=None, batch_id=None, estimated_effort="m",
                tags=["vdd", "pfl-277", "p17-b18"], metadata=None, deadline_at=None,
                verifications=[{
                    "type": "pytest",
                    "description": "全量 pytest 零回归 + 新增回归测试「worker 已发非回复消息 → mention 仍判未读」",
                }],
                actor_type="system", actor_id="system", team_id=project.team_id,
            )
            task.status = "ready"
            await db.commit()
            print(f"✅ Task: {task.title} ({task.id}) · status=ready（待 builder claim）")

        # .env + skill（worker cwd = worktree 根）
        if not args.dry_run and worker is not None and api_key != "ALREADY_REGISTERED":
            claude_dir = WORKER_DIR / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            (claude_dir / ".env").write_text(
                f"# Synapse Worker — {WORKER_NAME}\n"
                f"SYNAPSE_API_KEY={api_key}\n"
                f"SYNAPSE_API_URL={API_URL}\n"
                f"SYNAPSE_PROJECT_ID={project.id}\n"
                f"SYNAPSE_TEAM_ID={team.id}\n"
                f"SYNAPSE_WORKER_ID={worker.id}\n"
                f"SYNAPSE_WORKER_ROLE={WORKER_ROLE}\n"
            )
            print(f"✅ .env → {claude_dir / '.env'}")

            gen_script = Path(__file__).resolve().parent / "generate-skill.sh"
            if gen_script.exists():
                r = subprocess.run(
                    ["bash", str(gen_script), "--from-api",
                     "--output", str(WORKER_DIR),
                     "--api-url", API_URL,
                     "--worker-id", worker.id,
                     "--project-id", project.id,
                     "--role", WORKER_ROLE,
                     "--api-key", api_key],
                    capture_output=True, text=True,
                )
                print(f"✅ generate-skill.sh → {WORKER_DIR}" if r.returncode == 0
                      else f"⚠️  generate-skill.sh failed: {r.stderr[:400]}")
            else:
                print(f"⚠️  generate-skill.sh not found")

    print()
    print("=" * 60)
    print("🏁 P17-B18 VDD 环境就绪")
    print("=" * 60)
    print(f"   Worker:  {WORKER_NAME} (role={WORKER_ROLE})")
    print(f"   Worktree: {WORKER_DIR}")
    print(f"   Task:    {TASK_TITLE}")
    print(f"   API URL: {API_URL}")
    print()
    print("   🚨 worker 必须由用户在【独立终端】启动（B4-F6：God's-eye Bash 起会让")
    print("      worker 成为父会话子进程 · 方法学作废）。启动命令：")
    print(f"      bash tools/start-worker.sh --project-dir {WORKER_DIR}")
    print()
    print("   流程：builder claim VDD task → 改 src/ + 加回归测试 → 跑 pytest → submit")
    print("   → O（God's-eye）验收：审查 worktree 分支 diff → 合并 → 关 PFL-277")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
