#!/usr/bin/env python3
"""P100-B160 狗粮环境搭建：注册 O + Builder A + Builder B，创建 Project，生成 .env + skill。

改自 p16-b6-dogfood-setup.py。B160 差异：
  - Worker: P100-B160 O / A / B（A=后端 · B=前端 · 对应 P15 的 A/B 两 Builder）
  - Project: P100-B160 Snippet Vault Revalidation · phase P100 · batch B160 · slug p100-b160-snippet-vault
  - Worker cwd = worktree 根（O 为普通目录，A/B 为 git worktree）
  - 场景 = 重跑 P15 Snippet Vault 外部功能（1O+2B 交付后端+前端 · depends_on 串行）
    —— 验证 PFL-263/264/265/267 闭环后，自主 ✅/❌ 重判（见 p100-b160-autonomy-revalidation-plan.md）

B160 沿用 B6 的两个关键教训：
  git 不允许两个 worktree 检出同一分支 → B 的 worktree 推迟到 A 交付后再建，
  从彼时的 p100/b160-snippet-vault tip 拉独立分支 p100/b160-snippet-vault-b。
  human admin 是 post-login 步骤 → 本脚本只注册 agent Worker，不注册 human admin；
  human User 登录后再跑 `python tools/provision-human-admin.py --email <human-email>`（PFL-263 层3 · B159）。

Usage:
  cd synapse && .venv/bin/python tools/p100-b160-dogfood-setup.py
  # 分步注册（默认 o,a；A 交付后再补 b）：
  P160_SETUP_WORKERS=b .venv/bin/python tools/p100-b160-dogfood-setup.py
  # 干跑自检（不 commit · 不写 .env/skill · 事务 ROLLBACK 无副作用）：
  cd synapse && .venv/bin/python tools/p100-b160-dogfood-setup.py --dry-run
"""
import argparse
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
PROJECT_NAME = "P100-B160 Snippet Vault Revalidation"
PROJECT_SLUG = "p100-b160-snippet-vault"
PROJECT_DESC = (
    "P100-B160 自主性重验证：重跑 P15 Snippet Vault 场景（1O+2B 交付后端+前端），"
    "验证 PFL-263/264/265/267 闭环后执行环能否零 human turn + API 面零 human 授权介入。"
)

# 仓库根 = synapse/ 的上一级
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKTREES_DIR = REPO_ROOT / ".claude" / "worktrees"

# 分步注册（对齐 B160 分步跑法）：
#   Step1 只起 O，验拆解 → Step2 加 A，验 claim→execute→submit→verify（后端）
#   → Step3 加 B，验 depends_on 解锁（前端）。
# 用 P160_SETUP_WORKERS 环境变量控制本轮注册哪些（逗号分隔 o,a,b），默认 o,a。
_which = os.environ.get("P160_SETUP_WORKERS", "o,a").split(",")
_ALL = {
    "o": {"name": "P100-B160 O", "provider": "claude", "provider_model": "sonnet", "role": "orchestrator",
          "dir": WORKTREES_DIR / "p100-b160-o"},
    "a": {"name": "P100-B160 A", "provider": "claude", "provider_model": "sonnet", "role": "builder",
          "dir": WORKTREES_DIR / "p100-b160-a"},
    "b": {"name": "P100-B160 B", "provider": "claude", "provider_model": "sonnet", "role": "builder",
          "dir": WORKTREES_DIR / "p100-b160-b"},
}
WORKERS = [_ALL[k] for k in (w.strip() for w in _which) if k in _ALL]


async def main():
    parser = argparse.ArgumentParser(
        description="P100-B160 狗粮环境搭建：注册 O/A/B + Project + 生成 .env + skill",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的变更，不 commit、不写 .env/skill（无副作用干跑 · 对齐 B159 ROLLBACK 范式）",
    )
    args = parser.parse_args()
    dry_run = args.dry_run

    if not WORKERS:
        print(f"❌ P160_SETUP_WORKERS={_which!r} 未匹配任何 worker（可选 o,a,b）")
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
                use_phase_mode=True, current_phase="P100", organization=None,
                metadata={"phase": "P100", "batch": "B160"},
                is_protected=False, actor_type="system", actor_id="system",
            )
            if dry_run:
                print(f"🔍 [dry-run] would commit: Project {project.name} ({project.id})")
            else:
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
                if dry_run:
                    print(f"🔍 [dry-run] would register: {w['name']} ({worker_obj.id}) · Key（非持久）: {api_key}")
                else:
                    print(f"✅ Worker: {w['name']} ({worker_obj.id}) · Key: {api_key}")
        if dry_run:
            print(f"🔍 [dry-run] would commit: {len(results)} worker(s) + 项目角色（事务回滚 · 无副作用）")
        else:
            await db.commit()

        # 4. Generate .env + skill（worker cwd = worktree 根，.env 在 <dir>/.claude/.env）
        print()
        gen_script = Path(__file__).resolve().parent / "generate-skill.sh"
        for r in results:
            w = r["worker"]; name = w.name; api_key = r["api_key"]; role = r["role"]; wdir = r["dir"]
            if api_key == "ALREADY_REGISTERED":
                print(f"⚠️  {name}: 已存在，需手动获取 API key，跳过 .env")
                continue

            if dry_run:
                env_path = wdir / ".claude" / ".env"
                print(f"🔍 [dry-run] would write .env → {env_path}")
                if gen_script.exists():
                    print(f"🔍 [dry-run] would run generate-skill.sh → {wdir}")
                else:
                    print(f"⚠️  generate-skill.sh not found at {gen_script}")
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
    if dry_run:
        print(f"🔍 P100-B160 狗粮环境 dry-run 完成（本轮：{', '.join(w['name'] for w in WORKERS)}）· 未 commit · 无副作用")
    else:
        print(f"🏁 P100-B160 狗粮环境就绪（本轮：{', '.join(w['name'] for w in WORKERS)}）")
    print("=" * 60)
    print(f"   Team:    {team.name} ({team.id})")
    print(f"   Project: {project.name} ({project.id})")
    print(f"   API URL: {API_URL}")
    print()
    print("   🚨 worker 必须由用户在【各自独立终端】启动 —— God's-eye 用 Bash 起")
    print("      会让 worker 成为父会话子进程，方法学作废（B4-F6 教训）。")
    print()
    start_worker = Path(__file__).resolve().parent / "start-worker.sh"
    for w in WORKERS:
        print(f"     {w['name']:14} bash {start_worker} --project-dir {w['dir']}")
    print()
    print("   ⚠️  human admin 预置（PFL-263 层3 · B159）：human 登录后执行")
    print("       python tools/provision-human-admin.py --email <human-email>")
    print("       （赋 admin 角色，否则无 human-in-the-loop 可解锁授权死锁）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
