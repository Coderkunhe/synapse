#!/usr/bin/env python3
"""B64 Step 1: 清理 B24/B25 E2E 测试残留 Agent。

删除所有 name 匹配以下模式的 Agent 及其关联数据（capability, token_usage）：
- B24Test
- B24 E2E Test Agent
- worker-0708-agent-1
- 产品经理-0708-*

保留：P9-B42 Dogfood Bot, B61 Dogfood Agent (×2), B61 Dogfood Agent v3
"""
import asyncio
import sys
from pathlib import Path

# Ensure synapse/ is on path (same as seed-synapse-project.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db import async_session_factory
from src.models.agent import Agent
from src.models.token_usage import TokenUsage
from src.models.capability import Capability


async def cleanup():
    async with async_session_factory() as session:
        # 1. 找到所有 B24 残留 Agent
        result = await session.execute(
            select(Agent.id, Agent.name).where(
                Agent.name.like("B24%")
                | (Agent.name == "B24Test")
                | (Agent.name == "worker-0708-agent-1")
                | Agent.name.like("产品经理-0708%")
            )
        )
        agents = result.all()
        agent_ids = [a[0] for a in agents]
        agent_names = set(a[1] for a in agents)

        print(f"找到 {len(agent_ids)} 个残留 Agent")
        for name in sorted(agent_names):
            count = sum(1 for a in agents if a[1] == name)
            print(f"  - {name}: {count}")

        if not agent_ids:
            print("没有需要清理的 Agent，退出。")
            return

        # 2. 删除关联的 capability（Agent 有 cascade="all, delete-orphan"，但显式删更安全）
        cap_result = await session.execute(
            delete(Capability).where(Capability.agent_id.in_(agent_ids))
        )
        print(f"\n删除 {cap_result.rowcount} 条 capability 记录")

        # 3. 删除关联的 token_usage（没有 cascade，必须手动删）
        tu_result = await session.execute(
            delete(TokenUsage).where(TokenUsage.agent_id.in_(agent_ids))
        )
        print(f"删除 {tu_result.rowcount} 条 token_usage 记录")

        # 4. 删除 Agent
        agent_result = await session.execute(
            delete(Agent).where(Agent.id.in_(agent_ids))
        )
        print(f"删除 {agent_result.rowcount} 个 Agent")

        await session.commit()

        # 5. 验证
        result = await session.execute(select(Agent.id).where(Agent.id.in_(agent_ids)))
        remaining = result.all()
        if remaining:
            print(f"⚠️ 仍有 {len(remaining)} 个 Agent 未删除")
        else:
            print("\n✅ 清理完成！")

        # 显示剩余 Agent 数量
        result = await session.execute(select(Agent.id))
        total = len(result.all())
        print(f"当前 Agent 总数: {total}")


if __name__ == "__main__":
    asyncio.run(cleanup())
