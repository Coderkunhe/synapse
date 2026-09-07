#!/usr/bin/env python3
"""为 human User 在 Project 中赋予 admin 角色（PFL-263 层3 · post-login 步骤）。

背景：human User/Worker 只在 OAuth/注册登录后才存在 → 赋角色必须是 post-login
步骤，不能塞进 dogfood-setup 的初始注册段（PFL-263 层3 根因）。本脚本提供一条
可复现的「post-login 赋 admin」路径（P12-3 脚本化优先 + DG-2 可复现），根治
「狗粮项目无 human admin → human-in-the-loop 门禁变成等一个不存在的人」的死锁。

幂等：set_project_role 是 upsert（角色未变直接返回），重跑安全。

用法：
    python3 tools/provision-human-admin.py --email hunter@synapse.local
    python3 tools/provision-human-admin.py --name Hunter --project-slug p16-b6-dogfood
    python3 tools/provision-human-admin.py --email hunter@synapse.local --dry-run
"""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import func, select

from src.db import async_session_factory
from src.models.project import Project
from src.models.user import User
from src.models.worker import Worker
from src.services.project_role_service import set_project_role


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="为 human User 在 Project 中赋予 admin 角色（post-login · PFL-263 层3）",
    )
    ident = parser.add_mutually_exclusive_group(required=True)
    ident.add_argument("--email", help="human User 的登录邮箱（匹配 User.email）")
    ident.add_argument("--name", help="human Worker 的 display_name（匹配 Worker.name）")
    parser.add_argument(
        "--project-slug",
        default="p16-b6-dogfood",
        help="目标 Project 的 slug（默认 p16-b6-dogfood）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的变更，不 commit（幂等/干跑验证用）",
    )
    args = parser.parse_args()

    async with async_session_factory() as db:
        # 1. 查 human Worker（按 email 或 name）
        if args.email:
            email = args.email.strip().lower()
            result = await db.execute(
                select(Worker)
                .join(User, User.id == Worker.user_id)
                .where(Worker.actor_type == "human", func.lower(User.email) == email)
            )
        else:
            result = await db.execute(
                select(Worker).where(Worker.actor_type == "human", Worker.name == args.name)
            )
        worker = result.scalar_one_or_none()
        if worker is None:
            key = f"email={args.email}" if args.email else f"name={args.name}"
            print(f"❌ 找不到 human Worker（{key}）")
            print("   提示：human User/Worker 只在登录后存在，请先完成一次 OAuth/注册登录。")
            return 1
        print(f"✅ human Worker: {worker.name} ({worker.id})")

        # 2. 查 Project（按 slug）
        result = await db.execute(select(Project).where(Project.slug == args.project_slug))
        project = result.scalar_one_or_none()
        if project is None:
            print(f"❌ 找不到 Project（slug={args.project_slug}）")
            return 1
        print(f"✅ Project: {project.name} ({project.id})")

        # 3. 赋 admin 角色（upsert · 幂等）
        if args.dry_run:
            print(
                f"🔍 [dry-run] 将执行：set_project_role("
                f"project={project.id}, worker={worker.id}, role=admin)"
            )
        else:
            await set_project_role(
                db,
                project_id=project.id,
                worker_id=worker.id,
                role="admin",
                team_id=project.team_id,
                actor_type="system",
                actor_id="system",
            )
            await db.commit()
            print(f"✅ 已赋 admin 角色：worker={worker.id} → project={project.id}")

        print()
        print("=" * 60)
        print("🎉 human admin 预置完成" if not args.dry_run else "🔍 dry-run 完成（未 commit）")
        print()
        print(f"   Project: {project.name} ({project.slug})")
        print(f"   Admin:   {worker.name} ({worker.id})")
        print()
        print("   human 登录 Web UI 后即可在 /approvals 审批授权请求（PFL-263 层3）。")
        print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
