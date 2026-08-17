#!/usr/bin/env python3
"""P15-B2 环境重建 — 全新重建「post-B1、pre-B2」协调层状态。

背景：B1 环境在 2026-08-17 14:14 被清理（DB 清空 + worktree 删除，备份在
data/backups/synapse-2026-08-17-141408-before-p15-cleanup.db）。本脚本从零重建
协调层，供 Builder B 认领 Task B（前端）。B1 的代码交付在 git
（p15/snippet-vault @ f5d9ef4），不受影响。

与 p15-dogfood-setup.py（B1）差异：
  - 注册 3 Worker：O + A + B（A 后端已完成，仅作记录，不写 .env）
  - 重建 Task A（completed）+ Task B（ready, depends_on A）— 直接落库还原
    B1 的 completed/ready 状态。真实验证发生在 B1（git f5d9ef4），此处仅
    还原协调层簿记，不伪造验证事件。
  - .env + skill 只写给 O 和 B（A 已完成不需要）。

Usage:
  cd synapse && .venv/bin/python tools/p15-b2-setup.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.constants import ActorType, OwnerType, TaskStatus
from src.models.team import Team
from src.models.project import Project
from src.models.worker import Worker
from src.models.task import Task
from src.services.worker_service import register_worker
from src.services.project_service import create_project
from src.services.task_create import create_task as create_task_svc

DB_URL = os.environ.get("SYNAPSE_DB_URL", "sqlite+aiosqlite:///./data/synapse.db")
API_URL = "http://localhost:8000"
TEAM_SLUG = "synapse-core"
PROJECT_NAME = "P15-B1 Snippet Vault"
PROJECT_SLUG = "p15-b1-snippet-vault"
PROJECT_DESC = "P15-B1 战略验证：独立外部功能 Snippet Vault · 1O+2B 协作 · 后端 → 前端 depends_on"

# 仓库根 = synapse/ 的上一级（snippet-vault/ 与 synapse/ 平级处）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKTREES_DIR = REPO_ROOT / ".claude" / "worktrees"

# B2 重建全部 3 个 Worker（O + A + B）。A 已完成，bootstrap=False 不写 .env。
WORKERS = [
    {"name": "P15-B1 O", "provider": "claude", "provider_model": "sonnet",
     "role": "orchestrator", "dir": WORKTREES_DIR / "p15-o", "bootstrap": True},
    {"name": "P15-B1 A", "provider": "claude", "provider_model": "sonnet",
     "role": "builder", "dir": WORKTREES_DIR / "p15-a", "bootstrap": False},
    {"name": "P15-B1 B", "provider": "claude", "provider_model": "sonnet",
     "role": "builder", "dir": WORKTREES_DIR / "p15-b", "bootstrap": True},
]

# ── Task 定义（还原 B1 的两个 Task）──────────────────────────
TASK_A = {
    "title": "Snippet Vault 后端 — 6 端点 CRUD + search + SQLite + pytest",
    "description": (
        "在 snippet-vault/backend/ 交付独立外部功能后端。契约：6 个端点\n"
        "（snippet 的 create/read/update/delete/list/search），SQLite 持久化，\n"
        "pytest 覆盖 CRUD + search。硬约束：snippet-vault/ 不 import 任何\n"
        "synapse/src 或 synapse/frontend/src。\n\n"
        "已交付：git p15/snippet-vault @ f5d9ef4（13 tests 零回归）。"
    ),
    "priority": "p1",
    "estimated_effort": "m",
    "verifications": [],
}

TASK_B = {
    "title": "Snippet Vault 前端 — 三态 UI（列表/编辑器/搜索）+ 标签筛选",
    "description": (
        "在 snippet-vault/frontend/ 交付前端。三态 UI：列表（snippet 一览）、\n"
        "编辑器（新建/编辑 snippet）、搜索（关键词 + 标签筛选）。通过后端 6\n"
        "端点读写数据。硬约束：snippet-vault/ 不 import 任何 synapse/src 或\n"
        "synapse/frontend/src。栈由 Builder 自选（建议 Vite + React）。"
    ),
    "priority": "p1",
    "estimated_effort": "m",
    "verifications": [
        {
            "type": "manual",
            "description": (
                "npm run build 0 错误 + 前端可运行：列表/编辑器/搜索三态切换正常，"
                "标签筛选可过滤，CRUD 与后端 6 端点连通"
            ),
            "criteria": {},
            "expected_evidence_type": "code",
            "auto_verifiable": False,
            "auto_pass_pattern": None,
            "auto_fail_pattern": None,
        },
    ],
}


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

        # 2. Project（重建，get-or-create）
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

        # 3. 注册 3 Worker（get-or-create）
        workers_by_name: dict[str, Worker] = {}
        bootstrap_workers: list[tuple[Worker, str, str, Path]] = []  # (worker, api_key, role, dir)
        for w in WORKERS:
            existing_w = await db.execute(
                select(Worker).where(Worker.name == w["name"], Worker.team_id == team.id)
            )
            worker = existing_w.scalar_one_or_none()
            if worker:
                print(f"⏭️  Worker exists: {w['name']} ({worker.id})")
                # 已存在则无法拿回明文 key，跳过 .env（需人工处理）
                workers_by_name[w["name"]] = worker
                continue
            worker, api_key = await register_worker(
                db, team_id=team.id, name=w["name"], provider=w["provider"],
                provider_model=w["provider_model"], system_prompt=None,
                metadata={"worker_version": "0.0.0", "supported_events": []},
                registered_by="system", actor_type="agent", actor_id="system",
                batch_size=1, project_id=project.id, project_role=w["role"],
            )
            workers_by_name[w["name"]] = worker
            if w["bootstrap"]:
                bootstrap_workers.append((worker, api_key, w["role"], w["dir"]))
            print(f"✅ Worker: {w['name']} ({worker.id}) · Key: {api_key}")
        await db.commit()

        worker_o = workers_by_name["P15-B1 O"]
        worker_a = workers_by_name["P15-B1 A"]

        # 4. 重建 Task A（completed）+ Task B（ready, depends_on A）
        #    直接落库还原 B1 状态——真实验证在 git，此处不伪造事件/验证历史。
        existing_tasks = await db.execute(
            select(Task).where(Task.project_id == project.id)
        )
        if existing_tasks.scalars().first() is not None:
            print("⚠️  Project 已有 Task，跳过 Task 重建")
        else:
            task_a = await create_task_svc(
                db, project_id=project.id, title=TASK_A["title"],
                description=TASK_A["description"], priority=TASK_A["priority"],
                parent_task_id=None, batch_id=None,
                estimated_effort=TASK_A["estimated_effort"], tags=["backend"],
                required_capabilities=None, metadata={"phase": "P15", "batch": "B1"},
                deadline_at=None, verifications=TASK_A["verifications"],
                actor_type=ActorType.WORKER, actor_id=worker_o.id, team_id=team.id,
                depends_on=None,
            )
            # 还原 B1 的 completed 状态
            task_a.status = TaskStatus.COMPLETED
            task_a.owner_type = OwnerType.WORKER
            task_a.owner_id = worker_a.id
            task_a.completed_at = datetime.now(timezone.utc)
            print(f"✅ Task A (reconstructed completed): {task_a.id}")

            task_b = await create_task_svc(
                db, project_id=project.id, title=TASK_B["title"],
                description=TASK_B["description"], priority=TASK_B["priority"],
                parent_task_id=None, batch_id=None,
                estimated_effort=TASK_B["estimated_effort"], tags=["frontend"],
                required_capabilities=None, metadata={"phase": "P15", "batch": "B2"},
                deadline_at=None, verifications=TASK_B["verifications"],
                actor_type=ActorType.WORKER, actor_id=worker_o.id, team_id=team.id,
                depends_on=[{"task_id": task_a.id, "type": "sequential"}],
            )
            # 还原 B1 的 ready 状态（依赖 Task A 已满足）
            task_b.status = TaskStatus.READY
            print(f"✅ Task B (reconstructed ready): {task_b.id} · depends_on {task_a.id}")
            await db.commit()

        # 5. 写 .env + skill（仅 O 和 B）
        print()
        gen_script = Path(__file__).resolve().parent / "generate-skill.sh"
        for worker, api_key, role, wdir in bootstrap_workers:
            claude_dir = wdir / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            env_path = claude_dir / ".env"
            env_path.write_text(
                f"# Synapse Worker — {worker.name}\n"
                f"SYNAPSE_API_KEY={api_key}\n"
                f"SYNAPSE_API_URL={API_URL}\n"
                f"SYNAPSE_PROJECT_ID={project.id}\n"
                f"SYNAPSE_TEAM_ID={team.id}\n"
                f"SYNAPSE_WORKER_ID={worker.id}\n"
                f"SYNAPSE_WORKER_ROLE={role}\n"
            )
            print(f"✅ .env → {env_path}")

            if gen_script.exists():
                import subprocess
                result = subprocess.run(
                    ["bash", str(gen_script), "--from-api",
                     "--output", str(wdir),
                     "--api-url", API_URL,
                     "--worker-id", worker.id,
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
    print("🏁 P15-B2 环境重建就绪（O + A + B）")
    print("=" * 60)
    print(f"   Team:    {team.name} ({team.id})")
    print(f"   Project: {project.name} ({project.id})")
    print(f"   API URL: {API_URL}")
    print(f"   Task A:  completed (后端已在 git f5d9ef4)")
    print(f"   Task B:  ready (前端，待 Builder B 认领)")
    print()
    print("   下一步开窗口：")
    print(f"     O 窗口:  cd {WORKTREES_DIR}/p15-o && claude")
    print(f"     B 窗口:  cd {WORKTREES_DIR}/p15-b && claude")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
