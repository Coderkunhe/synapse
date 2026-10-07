#!/usr/bin/env python3
"""P17-B19 @mention 唤醒延迟 dogfood 环境搭建（PFL-278 blade 1 验证）。

验证目标：start-worker.sh idle 固定 5s 轮询（blade 1 砍掉指数退避）→ @mention 后
worker 在 ≤5s（一次轮询内）被 respond_to_mention 唤醒（vs 旧 backoff 等待 ~106s）。
唤醒总延迟 193s → ~92s（剩余 ~87s 是 claude -p 处理地板，留给 blade 2 daemon）。

与 B17 dogfood 的关键差异：
  - B17 验证「respond_to_mention 能唤醒」（真人认领 + 真人 @mention · 8 判据 · B18 重跑 2/2）。
  - B19 验证「唤醒延迟的 poll 分量从 ~106s 砍到 ~5s」（blade 1 机械变更落地），
    全程脚本化（DG-2 可复现 · 无需真人 UI），@mention 走真实 create_message API。

设计决策：
  - Project 复用 seed `synapse`（B4/B11/B17 同款 · 最小改动易善后）。
  - 注册两个 builder：
    - target `p17-b19-builder` —— 被 @ 的对象，无可认领任务 → idle → 靠 mention 唤醒。
    - sender `p17-b19-sender` —— 持 API key 走 POST .../messages 发 @mention
      （project_role=builder → task:comment 权限 · 非 self-@ 故 count_unread_mentions 计为未读）。
  - Task 建为 in_progress + human-owned（非 ready → 不被 claim → target 稳落 idle）。
  - sender 不跑 claude -p，只作 API 发件人；target 才跑 start-worker.sh。

幂等：worker 按 name 去重、task 按 (project_id, title) 去重。首次运行会把两个 worker 的
API key 写入各自 `.claude/.env`（sender 的 key 供后续发 mention 用）。

Usage:
  cd synapse && .venv/bin/python tools/p17-b19-dogfood-setup.py [--dry-run]
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

TARGET_NAME = "p17-b19-builder"  # 被 @ 的对象（无空格 → @worker:p17-b19-builder 精确匹配）
SENDER_NAME = "p17-b19-sender"   # 发 @mention 的 API 发件人
ROLE = "builder"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # ai-synapse/
TARGET_DIR = REPO_ROOT / ".claude" / "worktrees" / TARGET_NAME
SENDER_DIR = REPO_ROOT / ".claude" / "worktrees" / SENDER_NAME

TASK_TITLE = "P17-B19 @mention 唤醒延迟狗粮任务"
TASK_SPEC = """# P17-B19 @mention 唤醒延迟狗粮任务

这是 P17-B19（PFL-278 blade 1）的唤醒延迟 dogfood 验证任务。验证 start-worker.sh
idle 固定 5s 轮询（砍掉指数退避）后，@mention 唤醒的 poll 分量从 ~106s 降到 ~5s。

本任务为 in_progress + human-owned（非 ready），target builder 无可认领 → 稳落 idle。
sender builder 走 API 发 @mention，target 靠 respond_to_mention 唤醒（B13 链路）。
"""


def _write_env(worker_dir: Path, *, worker_name: str, api_key: str, worker_id: str,
               project_id: str, team_id: str) -> None:
    claude_dir = worker_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / ".env").write_text(
        f"# Synapse Worker — {worker_name}\n"
        f"SYNAPSE_API_KEY={api_key}\n"
        f"SYNAPSE_API_URL={API_URL}\n"
        f"SYNAPSE_PROJECT_ID={project_id}\n"
        f"SYNAPSE_TEAM_ID={team_id}\n"
        f"SYNAPSE_WORKER_ID={worker_id}\n"
        f"SYNAPSE_WORKER_ROLE={ROLE}\n"
    )


async def _register(db: AsyncSession, team_id: str, project_id: str, name: str,
                    dry_run: bool) -> tuple[Worker | None, str]:
    """注册单个 builder worker（幂等），返回 (worker, api_key)。

    已存在时 api_key 返回 "ALREADY_REGISTERED"（key 只存 OS 密钥链，注册后不落盘明文）。
    """
    worker = (await db.execute(
        select(Worker).where(Worker.name == name, Worker.team_id == team_id)
    )).scalar_one_or_none()
    if worker:
        print(f"⏭️  Worker exists: {worker.name} ({worker.id})")
        return worker, "ALREADY_REGISTERED"
    if dry_run:
        print(f"🔍 [dry-run] 将注册 Worker: {name}")
        return None, ""
    worker, api_key = await register_worker(
        db, team_id=team_id, name=name, provider="claude",
        provider_model="sonnet", system_prompt=None,
        metadata={"worker_version": "0.0.0", "supported_events": []},
        registered_by="system", actor_type="agent", actor_id="system",
        batch_size=1, project_id=project_id, project_role=ROLE,
    )
    await db.commit()
    print(f"✅ Worker: {worker.name} ({worker.id}) · Key: {api_key[:12]}...")
    return worker, api_key


async def main() -> int:
    parser = argparse.ArgumentParser(description="P17-B19 dogfood 环境搭建（幂等）")
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

        # 3. 注册 target + sender builder
        target, target_key = await _register(db, team.id, project.id, TARGET_NAME, args.dry_run)
        sender, sender_key = await _register(db, team.id, project.id, SENDER_NAME, args.dry_run)

        # 4. human owner（Hunter）—— task 归 human，target 无可认领
        hunter = (await db.execute(
            select(Worker).where(Worker.actor_type == "human", Worker.name == "Hunter")
        )).scalar_one_or_none()
        if not hunter:
            print("⚠️  Hunter (human) worker 未找到 —— task owner 将留空")
        hunter_id = hunter.id if hunter else None

        # 5. Task（幂等 · in_progress + human-owned · 非 ready 不被 claim）
        task = (await db.execute(
            select(Task).where(Task.project_id == project.id, Task.title == TASK_TITLE)
        )).scalar_one_or_none()
        if task:
            print(f"⏭️  Task exists: {task.id} · status={task.status} · owner_type={task.owner_type}")
        elif args.dry_run:
            print(f"🔍 [dry-run] 将创建 in_progress human-owned task: {TASK_TITLE}")
        else:
            task = await task_service.create_task(
                db, project_id=project.id, title=TASK_TITLE, description=TASK_SPEC,
                priority="p2", parent_task_id=None, batch_id=None, estimated_effort="s",
                tags=["dogfood", "p17-b19"], metadata=None, deadline_at=None,
                verifications=[{
                    "type": "manual",
                    "description": "target builder idle 固定 5s 轮询下，@mention 在 ≤5s 内触发 respond_to_mention",
                }],
                actor_type="system", actor_id="system", team_id=project.team_id,
            )
            task.status = "in_progress"
            task.owner_type = "human"
            if hunter_id:
                task.owner_id = hunter_id
            await db.commit()
            print(f"✅ Task: {task.title} ({task.id}) · status=in_progress · owner_type=human")

        # 6. .env（两个 worker 目录 · target 供 start-worker.sh · sender 供发 mention）
        if not args.dry_run:
            if target is not None and target_key != "ALREADY_REGISTERED":
                _write_env(TARGET_DIR, worker_name=TARGET_NAME, api_key=target_key,
                           worker_id=target.id, project_id=project.id, team_id=team.id)
                print(f"✅ target .env → {TARGET_DIR / '.claude' / '.env'}")
            if sender is not None and sender_key != "ALREADY_REGISTERED":
                _write_env(SENDER_DIR, worker_name=SENDER_NAME, api_key=sender_key,
                           worker_id=sender.id, project_id=project.id, team_id=team.id)
                print(f"✅ sender .env → {SENDER_DIR / '.claude' / '.env'}")

            # 7. generate-skill（仅 target · 需 claude -p 读 SKILL.md · server 必须已起）
            if target is not None and target_key != "ALREADY_REGISTERED":
                gen_script = Path(__file__).resolve().parent / "generate-skill.sh"
                if gen_script.exists():
                    r = subprocess.run(
                        ["bash", str(gen_script), "--from-api", "--output", str(TARGET_DIR),
                         "--api-url", API_URL, "--worker-id", target.id,
                         "--project-id", project.id, "--role", ROLE, "--api-key", target_key],
                        capture_output=True, text=True,
                    )
                    print(f"✅ generate-skill.sh → {TARGET_DIR}" if r.returncode == 0
                          else f"⚠️  generate-skill.sh failed: {r.stderr[:400]}")
                else:
                    print("⚠️  generate-skill.sh not found")

    print()
    print("=" * 60)
    print("🏁 P17-B19 狗粮环境就绪")
    print("=" * 60)
    print(f"   Project: {project.name} ({project.id})")
    print(f"   Target:  {TARGET_NAME} (idle → 被 @ 唤醒)")
    print(f"   Sender:  {SENDER_NAME} (发 @mention)")
    print(f"   Task:    {TASK_TITLE}")
    print()
    print("   关键顺序（target 必须 idle · 当前 project 0 ready task）：")
    print(f"     1. 起 target：bash tools/start-worker.sh --project-dir {TARGET_DIR}（观察 idle poll 5s）")
    print(f"     2. 发 mention：用 {SENDER_DIR / '.claude' / '.env'} 里的 key POST .../messages")
    print(f"     3. 观察 target 日志 idle → respond_to_mention（≤5s）→ claude -p 真回")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
