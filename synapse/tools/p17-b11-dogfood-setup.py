#!/usr/bin/env python3
"""P17-B11 会话生命周期 dogfood 环境搭建。

单 builder worker（headless）+ 复用 seed 项目 + 1 条 READY task。
验证链路：真人 @worker:p17-b11-builder → mention 投递（B8）→ worker 真回（预判 🔴）→ resolve（B9）。

设计决策：
  - Project 复用 seed `synapse`（B4 同款 · 最小改动易善后），不新建 project。
  - Worker 名 `p17-b11-builder` 无空格 —— parse_mentions 用 `\\S+`，空格会截断 LIKE 匹配。
  - Worker 目录用 `.claude/worktrees/p17-b11-builder` 普通目录（非 git worktree）——
    B11 worker 不写代码，仅需隔离（DG-1 意图），无需 checkout 全量代码。

幂等：worker 按 name 去重、task 按 (project_id, title) 去重。

Usage:
  cd synapse && .venv/bin/python tools/p17-b11-dogfood-setup.py [--dry-run]
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
WORKER_NAME = "p17-b11-builder"  # 无空格 → @worker:p17-b11-builder 精确匹配
WORKER_ROLE = "builder"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # ai-synapse/
WORKER_DIR = REPO_ROOT / ".claude" / "worktrees" / "p17-b11-builder"

TASK_TITLE = "P17-B11 会话生命周期狗粮任务"
TASK_SPEC = """# P17-B11 会话生命周期狗粮任务

这是 P17-B11 的会话生命周期 dogfood 验证任务。目标：验证真人 @mention agent worker 后，
worker 能收到 mention 并真实回复（非 God's-eye 代劳）。

## 你（真人）需要做的
1. 打开本任务详情页。
2. 在「协作消息」面板发一条消息，正文包含 `@worker:p17-b11-builder`（@mention 该 builder worker），
   例如："@worker:p17-b11-builder 请介绍一下你自己，确认你在线。"
3. 观察 worker 是否回复（真实 agent 回复，非手动代劳）。
4. 无论 worker 是否回复，点「resolve」收口本任务。

## 判定
- 消息落库且 mentions_json 含 worker_id → mention 解析 ✅（B8）
- worker 真回 → 会话生命周期闭环 ✅（预判 🔴：headless worker 无 WS 消费 + state-router 无回复动作）
- resolve → is_resolved=true ✅（B9）
"""


async def main() -> int:
    parser = argparse.ArgumentParser(description="P17-B11 dogfood 环境搭建（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不 commit")
    args = parser.parse_args()

    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # 1. Team
        team = (await db.execute(select(Team).where(Team.slug == TEAM_SLUG))).scalar_one_or_none()
        if not team:
            print(f"❌ Team '{TEAM_SLUG}' not found")
            return 1
        print(f"✅ Team: {team.name} ({team.id})")

        # 2. Project（复用 seed）
        project = (await db.execute(
            select(Project).where(Project.team_id == team.id, Project.slug == PROJECT_SLUG)
        )).scalar_one_or_none()
        if not project:
            print(f"❌ Project '{PROJECT_SLUG}' not found")
            return 1
        print(f"✅ Project: {project.name} ({project.id})")

        # 3. Register builder worker（幂等）
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

        # 4. Task（幂等 · ready 供 worker claim）
        task = (await db.execute(
            select(Task).where(Task.project_id == project.id, Task.title == TASK_TITLE)
        )).scalar_one_or_none()
        if task:
            print(f"⏭️  Task exists: {task.id} · status={task.status} · owner_type={task.owner_type}")
        elif args.dry_run:
            print(f"🔍 [dry-run] 将创建 READY task: {TASK_TITLE}")
        else:
            task = await task_service.create_task(
                db, project_id=project.id, title=TASK_TITLE, description=TASK_SPEC,
                priority="p2", parent_task_id=None, batch_id=None, estimated_effort="s",
                tags=["dogfood", "p17-b11"], metadata=None, deadline_at=None,
                verifications=[{
                    "type": "manual",
                    "description": "真人 @mention builder worker 后，worker 收到 mention 并真实回复",
                }],
                actor_type="system", actor_id="system", team_id=project.team_id,
            )
            task.status = "ready"
            await db.commit()
            print(f"✅ Task: {task.title} ({task.id}) · status=ready")

        # 5. Worker 目录 + .env + skill
        if not args.dry_run and api_key != "ALREADY_REGISTERED":
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
                    ["bash", str(gen_script), "--from-api", "--output", str(WORKER_DIR),
                     "--api-url", API_URL, "--worker-id", worker.id,
                     "--project-id", project.id, "--role", WORKER_ROLE, "--api-key", api_key],
                    capture_output=True, text=True,
                )
                print(f"✅ generate-skill.sh → {WORKER_DIR}" if r.returncode == 0
                      else f"⚠️  generate-skill.sh failed: {r.stderr[:400]}")
            else:
                print(f"⚠️  generate-skill.sh not found")

    print()
    print("=" * 60)
    print("🏁 P17-B11 狗粮环境就绪")
    print("=" * 60)
    print(f"   Project: {project.name} ({project.id})")
    print(f"   Worker:  {WORKER_NAME} (role={WORKER_ROLE})")
    print(f"   Task:    {TASK_TITLE}")
    print(f"   API URL: {API_URL}")
    print()
    print("   下一步：")
    print(f"     1. 起 server：.venv/bin/uvicorn src.main:app --port 8000 --reload")
    print(f"     2. 起前端：  cd frontend && npm run dev")
    print(f"     3. 起 worker：bash tools/start-worker.sh --project-dir {WORKER_DIR}")
    print("     4. 真人 Web UI 登录 → 打开 task → 发消息 @worker:p17-b11-builder")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
