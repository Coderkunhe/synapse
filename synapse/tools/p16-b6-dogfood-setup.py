#!/usr/bin/env python3
"""P16-B6 狗粮环境搭建：注册 O + Builder B1 + Builder B2，创建 Project，生成 .env + skill。

改自 p16-dogfood-setup.py（B4 版）。B6 差异：
  - Worker: P16-B6 O / B1 / B2
  - Project: P16-B6 Dogfood · phase P16 · batch B6 · slug p16-b6-dogfood
  - Worker cwd = worktree 根（O 为普通目录，B1/B2 为 git worktree）
  - 需求沿用 B4 的「Worker 心跳健康度观测」（B4 卡在 claim，该需求从未真正交付）

B6 专属注意（B4 未暴露的坑）：
  git 不允许两个 worktree 检出同一分支，所以 B4 计划 §3 里
      git worktree add <b1> -b p16/bN-dogfood
      git worktree add <b2>    p16/bN-dogfood   ← 必然失败
  是一条从未被执行过的死命令（B4 卡在 claim，没跑到 B2）。
  B6 改为：B2 的 worktree 推迟到 B1 交付后再建，从彼时的
  p16/b6-dogfood tip 拉独立分支 p16/b6-dogfood-b2 —— 既绕开限制，
  又让 B2 天然拿到 B1 的代码（depends_on 语义正好对上）。

Usage:
  cd synapse && .venv/bin/python tools/p16-b6-dogfood-setup.py
  # 分步注册（默认 o,b1；B1 交付后再补 b2）：
  P16_SETUP_WORKERS=b2 .venv/bin/python tools/p16-b6-dogfood-setup.py
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
PROJECT_NAME = "P16-B6 Dogfood"
PROJECT_SLUG = "p16-b6-dogfood"
PROJECT_DESC = (
    "P16-B6 狗粮重跑（多客户端）：验证 B5 修完 claim→execute 断裂后，"
    "执行环（O 拆/分/验 ⇄ B claim/execute/submit）能否零 human turn 跑完 · "
    "内部功能 Worker 心跳健康度观测"
)

# 仓库根 = synapse/ 的上一级
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKTREES_DIR = REPO_ROOT / ".claude" / "worktrees"

# 分步注册（对齐 B6 分步跑法）：
#   Step1 只起 O，验拆解 → Step2 加 B1，验 claim→execute→submit→verify
#   → Step3 加 B2，验 depends_on 解锁。
# 用 P16_SETUP_WORKERS 环境变量控制本轮注册哪些（逗号分隔 o,b1,b2），默认 o,b1。
_which = os.environ.get("P16_SETUP_WORKERS", "o,b1").split(",")
_ALL = {
    "o":  {"name": "P16-B6 O", "provider": "claude", "provider_model": "sonnet", "role": "orchestrator",
           "dir": WORKTREES_DIR / "p16-b6-o"},
    "b1": {"name": "P16-B6 B1", "provider": "claude", "provider_model": "sonnet", "role": "builder",
           "dir": WORKTREES_DIR / "p16-b6-b1"},
    "b2": {"name": "P16-B6 B2", "provider": "claude", "provider_model": "sonnet", "role": "builder",
           "dir": WORKTREES_DIR / "p16-b6-b2"},
}
WORKERS = [_ALL[k] for k in (w.strip() for w in _which) if k in _ALL]


async def main():
    if not WORKERS:
        print(f"❌ P16_SETUP_WORKERS={_which!r} 未匹配任何 worker（可选 o,b1,b2）")
        return 1

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
                metadata={"phase": "P16", "batch": "B6"},
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
            env_path.chmod(0o600)  # P11-B35 key 隔离：.env 权限 600
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
    print(f"🏁 P16-B6 狗粮环境就绪（本轮：{', '.join(w['name'] for w in WORKERS)}）")
    print("=" * 60)
    print(f"   Team:    {team.name} ({team.id})")
    print(f"   Project: {project.name} ({project.id})")
    print(f"   API URL: {API_URL}")
    print()
    print("   🚨 worker 必须由用户在【各自独立终端】启动 —— God's-eye 用 Bash 起")
    print("      会让 worker 成为父会话子进程，方法学作废（B4-F6 教训）。")
    print()
    for w in WORKERS:
        print(f"     {w['name']:12} bash tools/start-worker.sh --project-dir {w['dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
