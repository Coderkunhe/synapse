#!/usr/bin/env python3
"""P17-B34 VDD 环境搭建（UX 可发现性收口 · 纯前端批 · 0 src 后端）。

单 builder worker（headless · git worktree）+ 1 条 VDD task（spec = plan 文档）。
走 VDD 循环：God's-eye 建 Task → Builder 在 worktree 改 frontend/src + 跑 tsc/oxlint/e2e → O 验收。

与 P17-B18 VDD 的差异：
  - B18 改 src/ + pytest → 只 symlink .venv。
  - B34 改 frontend/src + tsc/oxlint/e2e → 额外 symlink frontend/node_modules。

设计决策：
  - worktree 在 `.claude/worktrees/p17-b34-builder`（分支 p17-b34-builder · DG-5 命名）。
  - worker 名 `p17-b34-builder`。
  - .venv symlink 到主 repo 的 synapse/.venv（worktree 不含 gitignored .venv）。
  - frontend/node_modules symlink 同理（worktree 不含 gitignored node_modules）。
  - VDD task 建为 ready（builder 起后走 claim→execute 正常执行环）。

幂等：worker 按 name 去重、task 按 (project_id, title) 去重、worktree 已存在则跳过。
--cleanup：精准删 p17-b34-* worker + P17-B34 标题 task + 关联数据（FK 安全序）+ worktree/branch。

Usage:
  cd synapse && .venv/bin/python tools/p17-b34-vdd-setup.py [--dry-run]
  cd synapse && .venv/bin/python tools/p17-b34-vdd-setup.py --cleanup  # 善后
"""
import argparse
import asyncio
import os
import sqlite3
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
WORKER_NAME = "p17-b34-builder"
WORKER_ROLE = "builder"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # ai-synapse/
SYNAPSE_ROOT = REPO_ROOT / "synapse"
WORKER_DIR = REPO_ROOT / ".claude" / "worktrees" / "p17-b34-builder"
BRANCH = "p17-b34-builder"
SPEC_PATH = SYNAPSE_ROOT / "docs" / "plans" / "p17-b34-ux-discoverability.md"

TASK_TITLE = "P17-B34 VDD：UX 可发现性收口（可认领前移首屏 + 项目详情任务列表 + 导航态势）"


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
    src_venv = SYNAPSE_ROOT / ".venv"
    dst_venv = WORKER_DIR / "synapse" / ".venv"
    if src_venv.exists() and not dst_venv.exists():
        dst_venv.symlink_to(src_venv, target_is_directory=True)
        print(f"✅ .venv symlink → {dst_venv}")

    # 共享 node_modules（B34 前端批需要 tsc/oxlint/e2e）
    src_nm = SYNAPSE_ROOT / "frontend" / "node_modules"
    dst_nm = WORKER_DIR / "synapse" / "frontend" / "node_modules"
    if src_nm.exists() and not dst_nm.exists():
        dst_nm.parent.mkdir(parents=True, exist_ok=True)
        dst_nm.symlink_to(src_nm, target_is_directory=True)
        print(f"✅ node_modules symlink → {dst_nm}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="P17-B34 VDD 环境搭建（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不 commit")
    args = parser.parse_args()

    if not args.dry_run:
        create_worktree()

    if not SPEC_PATH.exists():
        print(f"❌ VDD spec 不存在: {SPEC_PATH}")
        return 1
    spec_text = SPEC_PATH.read_text(encoding="utf-8")

    desc = (
        "P17-B34 VDD 任务（前端批 · 0 src 后端 · God's-eye 不写 frontend/src）。\n\n"
        "实现要求：\n"
        "1. 在 worktree 内改 frontend/src（约 7 文件）+ 1 e2e，严格按下方 plan 改动清单。\n"
        "2. 钉死 plan「关键风险」三点（?filter 不撞 ?tab=history · ?project 优先于 localStorage · 「可认领」= by_status.ready 近似语义）。\n"
        "3. 验证：tsc --noEmit 0 新增 · oxlint 0 新增（12 预存）· e2e 新增用例绿 · pytest 1059 基线不变（0 src）。\n"
        "4. commit 到分支 p17-b34-builder。\n\n"
        "--- plan 全文 ---\n"
        f"{spec_text}"
    )

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
                db, project_id=project.id, title=TASK_TITLE, description=desc,
                priority="p1", parent_task_id=None, batch_id=None, estimated_effort="m",
                tags=["vdd", "p17-b34", "ux-discoverability"], metadata=None, deadline_at=None,
                verifications=[{
                    "type": "check_list",
                    "description": "tsc 0 新增 · oxlint 0 新增 · e2e 深链/tasks-tab/nav 文案绿 · pytest 1059 基线不变 · 红绿变异（摘 ?filter 解析 → 深链变红）",
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

            gen_script = SYNAPSE_ROOT / "tools" / "generate-skill.sh"
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
    print("🏁 P17-B34 VDD 环境就绪")
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
    print("   流程：builder claim VDD task → 改 frontend/src + e2e → tsc/oxlint/e2e → submit")
    print("   → O（God's-eye）验收：审查 worktree diff → cherry-pick → 关 task")
    return 0


def _sqlite_db() -> sqlite3.Connection:
    db_path = SYNAPSE_ROOT / "data" / "synapse.db"
    if not db_path.exists():
        print(f"❌ DB 不存在: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def cleanup() -> int:
    """精准删除 p17-b34-* worker + P17-B34 标题 task + 关联数据（FK 安全序）+ worktree/branch。"""
    conn = _sqlite_db()

    worker_ids = [r[0] for r in conn.execute(
        "SELECT id FROM worker WHERE name LIKE 'p17-b34-%'"
    ).fetchall()]
    task_ids = [r[0] for r in conn.execute(
        "SELECT id FROM task WHERE title LIKE 'P17-B34 %'"
    ).fetchall()]

    print(f"  目标 worker: {len(worker_ids)} 条 · task: {len(task_ids)} 条")

    if worker_ids or task_ids:
        wp = ",".join("?" * len(worker_ids)) if worker_ids else "NULL"
        tp = ",".join("?" * len(task_ids)) if task_ids else "NULL"
        wparams = tuple(worker_ids)
        tparams = tuple(task_ids)

        steps = []
        if task_ids:
            steps += [
                ("event（target_id→task）", f"DELETE FROM event WHERE target_id IN ({tp})", tparams),
                ("verification", f"DELETE FROM verification WHERE task_id IN ({tp})", tparams),
                ("mention 关联行", f"DELETE FROM task_worker_conversation_mention WHERE conversation_id IN (SELECT id FROM task_worker_conversation WHERE task_id IN ({tp}))", tparams),
                ("task_worker_conversation", f"DELETE FROM task_worker_conversation WHERE task_id IN ({tp})", tparams),
                ("token_usage（task）", f"DELETE FROM token_usage WHERE task_id IN ({tp})", tparams),
                ("task.parent 置空", f"UPDATE task SET parent_task_id = NULL WHERE parent_task_id IN ({tp})", tparams),
                ("worker.active_task_id 置空", f"UPDATE worker SET active_task_id = NULL WHERE active_task_id IN ({tp})", tparams),
            ]
        if worker_ids:
            steps += [
                ("event（actor/target→worker）", f"DELETE FROM event WHERE actor_id IN ({wp}) OR target_id IN ({wp})", wparams + wparams),
                ("capability", f"DELETE FROM capability WHERE worker_id IN ({wp})", wparams),
                ("team_members", f"DELETE FROM team_members WHERE worker_id IN ({wp})", wparams),
                ("project_actor_roles", f"DELETE FROM project_actor_roles WHERE worker_id IN ({wp})", wparams),
                ("authorization_requests", f"DELETE FROM authorization_requests WHERE worker_id IN ({wp}) OR responded_by_worker_id IN ({wp})", wparams + wparams),
                ("workflow_role", f"DELETE FROM workflow_role WHERE worker_id IN ({wp})", wparams),
                ("decision_audits", f"DELETE FROM decision_audits WHERE worker_id IN ({wp})", wparams),
                ("capability_audits", f"DELETE FROM capability_audits WHERE worker_id IN ({wp})", wparams),
                ("token_usage（worker）", f"DELETE FROM token_usage WHERE worker_id IN ({wp})", wparams),
                ("task_worker_conversation（sender/resolved）", f"DELETE FROM task_worker_conversation WHERE sender_worker_id IN ({wp}) OR resolved_by_worker_id IN ({wp})", wparams + wparams),
                ("batch.assigned_worker_id 置空", f"UPDATE batch SET assigned_worker_id = NULL WHERE assigned_worker_id IN ({wp})", wparams),
                ("worker.registered_by 置空", f"UPDATE worker SET registered_by = NULL WHERE registered_by IN ({wp})", wparams),
            ]

        if task_ids:
            steps.append(("task", f"DELETE FROM task WHERE id IN ({tp})", tparams))
        if worker_ids:
            steps.append(("worker", f"DELETE FROM worker WHERE id IN ({wp})", wparams))

        try:
            for desc, sql, params in steps:
                cur = conn.execute(sql, params)
                print(f"    {desc}: {cur.rowcount} 条")
            conn.commit()
            print("\n  ✅ p17-b34 DB 残留已清理")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        print("  （无 p17-b34 残留，无需清理）")
        conn.close()

    # worktree + branch
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(WORKER_DIR)],
        capture_output=True, text=True,
    )
    print(f"  worktree remove: {'✅' if r.returncode == 0 else '⚠️ ' + r.stderr[:200]}")
    subprocess.run(["git", "-C", str(REPO_ROOT), "branch", "-D", BRANCH], capture_output=True, text=True)
    subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "prune"], capture_output=True, text=True)
    print("  ✅ worktree + branch 已清（如存在）")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P17-B34 VDD 环境搭建（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不 commit")
    parser.add_argument("--cleanup", action="store_true", help="善后：删 p17-b34-* 残留 + worktree/branch")
    args = parser.parse_args()
    if args.cleanup:
        sys.exit(cleanup())
    sys.exit(asyncio.run(main()))
