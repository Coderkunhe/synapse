#!/usr/bin/env python3
"""为 P17-B4 狗粮验证在 seed 项目里预置一条 READY task（DG-2 可复现 · 幂等）。

背景：P17-B4 要验证「真人认领 → 读规范 → 同步 → 提交」人机闭环。当前 DB 里
所有 task 都是终态（completed/cancelled/rejected），没有可认领的 READY task。
本脚本在 seed 项目 `synapse` 里幂等地创建一条 READY task，description 即「规范」，
供真人通过 Web UI 认领。

幂等：按 (project_id, title) 去重，已存在则跳过并打印现状。

用法：
    python3 tools/provision-b4-task.py
    python3 tools/provision-b4-task.py --dry-run
"""

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from sqlalchemy import select

from src.db import async_session_factory
from src.models.project import Project
from src.models.task import Task
from src.services import task_service

PROJECT_SLUG = "synapse"
TASK_TITLE = "P17-B4 人机闭环狗粮验证任务"

TASK_SPEC = """# P17-B4 人机闭环狗粮验证任务

这是 P17-B4 的狗粮验证任务。目标：验证真人（非 headless agent）能像 worker 一样
走完「认领 → 读规范 → 提交」闭环，且全程不被租约回收、不依赖 God's-eye 干预。

## 你需要做的
1. 阅读本规范（这就是「读规范」步骤）。
2. 点击「认领」按钮认领本任务。
3. 等待 >10 分钟（验证你不会被 lease 600s 回收踢出）。
4. 点击「提交」，summary 写一句你完成的内容（例如："已通过 Web UI 认领并提交，验证人机协作闭环"）。

## 判定
- 认领后 owner 是 human，且 >10min 不被回收 → 免死成立（P17-B2 owner_is_alive）。
- 提交后任务进入 in_verification → 闭环成立（P17-B3 最小闭环）。
"""


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="为 P17-B4 狗粮验证预置一条 READY task（幂等）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不 commit")
    args = parser.parse_args()

    async with async_session_factory() as db:
        # 1. 查 seed 项目
        result = await db.execute(select(Project).where(Project.slug == PROJECT_SLUG))
        project = result.scalar_one_or_none()
        if project is None:
            print(f"❌ 找不到 Project（slug={PROJECT_SLUG}）")
            return 1
        print(f"✅ Project: {project.name} ({project.id})")

        # 2. 幂等：按 (project_id, title) 去重
        result = await db.execute(
            select(Task).where(Task.project_id == project.id, Task.title == TASK_TITLE)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            print(f"⏭️  Task 已存在: {existing.id} · status={existing.status} · owner_type={existing.owner_type}")
            return 0

        if args.dry_run:
            print(f"🔍 [dry-run] 将创建 READY task: {TASK_TITLE}")
            return 0

        # 3. 经 service 创建（恒从 backlog 起），再置 ready（复用 seed 脚本 pattern）
        task = await task_service.create_task(
            db,
            project_id=project.id,
            title=TASK_TITLE,
            description=TASK_SPEC,
            priority="p2",
            parent_task_id=None,
            batch_id=None,
            estimated_effort="s",
            tags=["dogfood", "p17-b4"],
            metadata=None,
            deadline_at=None,
            verifications=[{
                "type": "manual",
                "description": "人机闭环验证：owner=human 且提交后 in_verification",
            }],
            actor_type="system",
            actor_id="system",
            team_id=project.team_id,
        )
        task.status = "ready"
        await db.commit()

        print()
        print("=" * 60)
        print("🎉 P17-B4 READY task 预置完成")
        print()
        print(f"   Task:    {task.title}")
        print(f"   ID:      {task.id}")
        print(f"   Project: {project.slug}")
        print(f"   Status:  {task.status}")
        print()
        print("   真人登录 Web UI 后在 Task 详情页即可「认领」本任务。")
        print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
