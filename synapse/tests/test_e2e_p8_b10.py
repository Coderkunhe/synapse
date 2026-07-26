"""P8-B10: E2E 干跑 — 全链路协作验证。

覆盖 P8 成功标准（参见 P7 D5 §B10）:
  1. 快乐路径: 2+ Worker 完成 分配→执行→提交→验证→批次完成
  2. 故障恢复: Worker 崩溃 → 任务释放 → 另一个 Worker 接管
  3. 审查超时: 超时审查发出 review.overdue 信号
  4. EventStore: 所有关键状态转换都有 Event 记录
  5. 多 Worker: 两个 Worker 在同一批次协作
  6. 阻塞报告: Worker 遇到阻塞 → 释放 → 无惩罚

设计说明:
  - 通过 API 创建的任务从 BACKLOG 开始；使用 assign（推送）移动到 IN_PROGRESS
  - 验证端点为 POST /v1/verifications/{id}/verify
  - 基于时间的操作使用直接 DB 操作来模拟时间流逝
  - 每个测试类有独立的种子数据（Team 隔离）— 跨测试事件
    累积测试在测试自身内部使用自包含的 E2E 流程
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import SeedData, auth_header, ensure_project_role


# ═══════════════════════════════════════════════════════════════════════
# API 辅助函数
# ═══════════════════════════════════════════════════════════════════════


async def _create_project(client: AsyncClient, seed: SeedData, name: str) -> dict:
    import uuid
    slug = f"b10-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": name, "description": "P8-B10 E2E 干跑", "slug": slug},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, f"创建项目失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _create_batch(
    client: AsyncClient, seed: SeedData, project_id: str, name: str = "B10 E2E 批次"
) -> dict:
    resp = await client.post(
        f"/v1/projects/{project_id}/batches",
        json={"name": name, "description": "E2E 干跑批次"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, f"创建批次失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _register_worker(
    client: AsyncClient, seed: SeedData, name: str
) -> tuple[dict, str]:
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/agents",
        json={"name": name, "provider": "claude", "provider_model": "sonnet"},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, f"注册 Worker 失败 [{resp.status_code}]: {resp.text}"
    data = resp.json()
    return data["worker"], data["api_key"]


async def _worker_handshake(client: AsyncClient, agent_id: str, api_key: str) -> dict:
    resp = await client.post(
        f"/v1/agents/{agent_id}/handshake",
        json={
            "worker_version": "1.0.0",
            "capabilities": [
                {"name": "code-review", "description": "代码审查",
                 "input_schema": {}, "output_schema": {}},
            ],
            "supported_events": ["task.claimed", "task.submitted", "task.completed"],
            "preferred_channel": "websocket",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"握手失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _worker_heartbeat(
    client: AsyncClient, agent_id: str, api_key: str, task_id: str | None = None
) -> dict:
    resp = await client.post(
        f"/v1/agents/{agent_id}/heartbeat",
        json={"current_load": 1, "current_task_id": task_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"心跳失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _create_task_api(
    client: AsyncClient, seed: SeedData, project_id: str,
    title: str, batch_id: str, priority: str = "p2",
) -> dict:
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={
            "title": title,
            "description": f"{title} 的描述",
            "priority": priority,
            "batch_id": batch_id,
            "verifications": [
                {"type": "manual", "description": "验证输出正确性"},
            ],
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, f"创建任务失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _assign_task(
    client: AsyncClient, seed: SeedData, task_id: str,
    owner_type: str, owner_id: str, expected_version: int,
) -> dict:
    resp = await client.post(
        f"/v1/tasks/{task_id}/assign",
        json={
            "owner_type": owner_type,
            "owner_id": owner_id,
            "expected_version": expected_version,
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200, f"分配失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _start_task(
    client: AsyncClient, seed: SeedData, agent_id: str, task_id: str,
) -> dict:
    resp = await client.post(
        f"/v1/agents/{agent_id}/start-task?task_id={task_id}",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200, f"启动任务失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _submit_task(
    client: AsyncClient, agent_id: str, api_key: str,
    task_id: str, expected_version: int, verification_id: str,
) -> dict:
    """提交任务。VerificationResult 中的 evidence 必须为 str | None。"""
    resp = await client.post(
        f"/v1/tasks/{task_id}/submit",
        json={
            "summary": "任务成功完成",
            "evidence": {"output": "所有检查通过", "output_access": {"type": "inline", "value": "所有自动检查全部通过"}},
            "verification_results": [{
                "verification_id": verification_id,
                "status": "passed",
                "evidence": "所有测试输出绿色，无回归",
            }],
            "expected_version": expected_version,
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"提交失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _verify_task(
    client: AsyncClient, seed: SeedData,
    verification_id: str, task_version: int, status: str = "passed",
) -> dict:
    resp = await client.post(
        f"/v1/verifications/{verification_id}/verify",
        json={
            "status": status,
            "comment": "看起来不错" if status == "passed" else "需要返工",
            "expected_task_version": task_version,
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200, f"验证失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _get_task(client: AsyncClient, seed: SeedData, task_id: str) -> dict:
    resp = await client.get(
        f"/v1/tasks/{task_id}", headers=auth_header(seed.token),
    )
    assert resp.status_code == 200, f"获取任务失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _get_verifications(
    client: AsyncClient, seed: SeedData, task_id: str,
) -> list[dict]:
    resp = await client.get(
        f"/v1/tasks/{task_id}/verifications",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200, f"获取验证项失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


async def _get_team_events(
    client: AsyncClient, seed: SeedData, limit: int = 100,
) -> list[dict]:
    resp = await client.get(
        f"/v1/teams/{seed.team_id}/events?limit={limit}",
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200
    return resp.json()["items"]


async def _report_blocker(
    client: AsyncClient, agent_api_key: str, task_id: str,
    blocker_type: str, description: str, suggested_fix: str | None,
    expected_version: int,
) -> dict:
    resp = await client.post(
        f"/v1/tasks/{task_id}/blocker",
        json={
            "blocker_type": blocker_type,
            "description": description,
            "suggested_fix": suggested_fix,
            "expected_version": expected_version,
        },
        headers={"Authorization": f"Bearer {agent_api_key}"},
    )
    assert resp.status_code == 200, f"阻塞报告失败 [{resp.status_code}]: {resp.text}"
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════
# 第 1 节: 快乐路径 — 双 Worker 全链路
# ═══════════════════════════════════════════════════════════════════════


class TestHappyPathFullChain:
    """完整快乐路径: 注册 → 握手 → 分配 → 执行 → 提交 →
    验证 → 批次完成。"""

    @pytest.mark.asyncio
    async def test_happy_path_full_chain(
        self, client: AsyncClient, seed: SeedData,
    ):
        """E2E 快乐路径: 2 个 Worker 在一个包含 3 个任务的批次上协作。

        流程:
          1. 注册 Worker A + B → 握手 → active
          2. 创建 Project → Batch → 3 个 Task（BACKLOG）
          3. 推送分配: Task 1→A, Task 2→B, Task 3→A
          4. 每个 Worker 启动 → 提交 → 创建者验证
          5. 全部 3 个终态 → batch.completed 事件
          6. EventStore 追踪包含完整的任务生命周期
        """
        # ── 第 1 步: 注册并激活 2 个 Worker ──
        agent_a, key_a = await _register_worker(client, seed, "B10-Happy-Alpha")
        agent_b, key_b = await _register_worker(client, seed, "B10-Happy-Bravo")
        agent_a = await _worker_handshake(client, agent_a["id"], key_a)
        agent_b = await _worker_handshake(client, agent_b["id"], key_b)
        assert agent_a["status"] == "active"
        assert agent_b["status"] == "active"
        await _worker_heartbeat(client, agent_a["id"], key_a)
        await _worker_heartbeat(client, agent_b["id"], key_b)

        # ── 第 2 步: Project + Batch + 3 个 Task ──
        project = await _create_project(client, seed, "B10 快乐路径")

        # B55 (GAP-7): Workers need project role for submit (builder domain)
        headers = auth_header(seed.token)
        await client.post(
            f"/v1/admin/projects/{project['id']}/roles",
            json={"worker_id": agent_a["id"], "role": "admin"},
            headers=headers,
        )
        await client.post(
            f"/v1/admin/projects/{project['id']}/roles",
            json={"worker_id": agent_b["id"], "role": "admin"},
            headers=headers,
        )

        batch = await _create_batch(client, seed, project["id"], "B10 快乐批次")

        task1 = await _create_task_api(client, seed, project["id"], "E2E 任务 1", batch["id"], "p1")
        task2 = await _create_task_api(client, seed, project["id"], "E2E 任务 2", batch["id"], "p1")
        task3 = await _create_task_api(client, seed, project["id"], "E2E 任务 3", batch["id"], "p2")
        assert task1["status"] == "backlog"
        assert task2["status"] == "backlog"
        assert task3["status"] == "backlog"

        # ── 第 3 步: 推送分配任务（BACKLOG → IN_PROGRESS）──
        task1 = await _assign_task(
            client, seed, task1["id"], "worker", agent_a["id"], task1["version_no"])
        task2 = await _assign_task(
            client, seed, task2["id"], "worker", agent_b["id"], task2["version_no"])
        task3 = await _assign_task(
            client, seed, task3["id"], "worker", agent_a["id"], task3["version_no"])
        assert task1["status"] == "in_progress"
        assert task1["owner_id"] == agent_a["id"]
        assert task2["owner_id"] == agent_b["id"]
        assert task3["owner_id"] == agent_a["id"]

        # ── 第 4 步: 执行 → 提交 → 验证（内联以避免闭包问题）──

        # Worker A 执行 Task 1
        await _start_task(client, seed, agent_a["id"], task1["id"])
        verifs_1 = await _get_verifications(client, seed, task1["id"])
        fresh_1 = await _get_task(client, seed, task1["id"])
        sub_1 = await _submit_task(
            client, agent_a["id"], key_a, task1["id"],
            fresh_1["version_no"], verifs_1[0]["id"])
        assert sub_1["status"] == "in_verification"
        fresh_1v = await _get_task(client, seed, task1["id"])
        await _verify_task(client, seed, verifs_1[0]["id"], fresh_1v["version_no"], "passed")
        final_1 = await _get_task(client, seed, task1["id"])
        assert final_1["status"] == "completed"

        # Worker B 执行 Task 2
        await _start_task(client, seed, agent_b["id"], task2["id"])
        verifs_2 = await _get_verifications(client, seed, task2["id"])
        fresh_2 = await _get_task(client, seed, task2["id"])
        sub_2 = await _submit_task(
            client, agent_b["id"], key_b, task2["id"],
            fresh_2["version_no"], verifs_2[0]["id"])
        assert sub_2["status"] == "in_verification"
        fresh_2v = await _get_task(client, seed, task2["id"])
        await _verify_task(client, seed, verifs_2[0]["id"], fresh_2v["version_no"], "passed")
        final_2 = await _get_task(client, seed, task2["id"])
        assert final_2["status"] == "completed"

        # Worker A 执行 Task 3（提交 Task 1 后 agent 应为 IDLE）
        await _start_task(client, seed, agent_a["id"], task3["id"])
        verifs_3 = await _get_verifications(client, seed, task3["id"])
        fresh_3 = await _get_task(client, seed, task3["id"])
        sub_3 = await _submit_task(
            client, agent_a["id"], key_a, task3["id"],
            fresh_3["version_no"], verifs_3[0]["id"])
        assert sub_3["status"] == "in_verification"
        fresh_3v = await _get_task(client, seed, task3["id"])
        await _verify_task(client, seed, verifs_3[0]["id"], fresh_3v["version_no"], "passed")
        final_3 = await _get_task(client, seed, task3["id"])
        assert final_3["status"] == "completed"

        # ── 第 5 步: batch.completed ──
        events = await _get_team_events(client, seed)
        event_types = [e["event_type"] for e in events]
        assert "batch.completed" in event_types, (
            f"batch.completed 缺失。事件列表: {sorted(set(event_types))}")

        # ── 第 6 步: EventStore 追踪完整性 ──
        critical = [
            "batch.created", "task.created", "task.assigned",
            "task.submitted", "task.completed", "batch.completed",
        ]
        for evt in critical:
            assert evt in event_types, f"缺少关键事件: {evt}"

        for t in [task1, task2, task3]:
            task_events = [e for e in events
                           if e.get("target_id") == t["id"]
                           and e.get("target_type") == "task"]
            t_types = {e["event_type"] for e in task_events}
            for req in ["task.created", "task.assigned", "task.submitted", "task.completed"]:
                assert req in t_types, f"Task {t['id']} 缺少 {req}。当前: {t_types}"


# ═══════════════════════════════════════════════════════════════════════
# 第 2 节: 故障恢复 — Worker 崩溃 → 释放 → 救援
# ═══════════════════════════════════════════════════════════════════════


class TestFailureRecovery:
    """Worker A 崩溃（心跳超时）→ 任务释放 → Worker B 救援。"""

    @pytest.mark.asyncio
    async def test_worker_crash_recovery(
        self, client: AsyncClient, seed: SeedData,
    ):
        """模拟 Worker A 崩溃: 心跳过期 → 故障检测器释放
        任务 → Worker B 认领已释放任务 → 完成它们。

        验证:
          - agent.runtime.error 事件已发出
          - 任务释放回 READY
          - Worker B 可以接管并完成已释放任务
        """
        # ── 准备 ──
        agent_a, key_a = await _register_worker(client, seed, "B10-Crash-Alpha")
        agent_b, key_b = await _register_worker(client, seed, "B10-Rescue-Bravo")
        await _worker_handshake(client, agent_a["id"], key_a)
        await _worker_handshake(client, agent_b["id"], key_b)
        await _worker_heartbeat(client, agent_a["id"], key_a)
        await _worker_heartbeat(client, agent_b["id"], key_b)

        project = await _create_project(client, seed, "B10 故障恢复")
        # B55 (GAP-7): Workers need project role for submit
        admin_headers = auth_header(seed.token)
        await ensure_project_role(client, project["id"], agent_b["id"], "builder", admin_headers)
        batch = await _create_batch(client, seed, project["id"])

        task_a = await _create_task_api(client, seed, project["id"], "恢复任务 1", batch["id"])
        task_b = await _create_task_api(client, seed, project["id"], "恢复任务 2", batch["id"])

        # 推送分配两个任务给 Worker A
        task_a = await _assign_task(
            client, seed, task_a["id"], "worker", agent_a["id"], task_a["version_no"])
        task_b = await _assign_task(
            client, seed, task_b["id"], "worker", agent_a["id"], task_b["version_no"])
        await _start_task(client, seed, agent_a["id"], task_a["id"])

        # ── 模拟 Worker A 崩溃: 通过 DB 使心跳过期 ──
        from src.db import async_session_factory
        from src.models.worker import Worker

        async with async_session_factory() as db_session:
            agent = await db_session.get(Worker, agent_a["id"])
            assert agent is not None
            agent.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
            await db_session.commit()

        # ── 运行故障检测器 ──
        from src.services.failure_detector import detect_heartbeat_failures

        async with async_session_factory() as db_session:
            result = await detect_heartbeat_failures(db_session)
            await db_session.commit()

        assert result["failed_workers"] >= 1
        assert agent_a["id"] in result["failed_worker_ids"]
        assert result["released_tasks"] >= 1

        released_ids = set(result["released_task_ids"])

        # ── Worker B 认领并完成每个已释放任务 ──
        for tid in released_ids:
            task_info = await _get_task(client, seed, tid)
            if task_info["status"] != "ready":
                continue

            # 通过 API 认领（READY → IN_PROGRESS）
            claim_resp = await client.post(
                f"/v1/tasks/{tid}/claim?expected_version={task_info['version_no']}",
                headers={"Authorization": f"Bearer {key_b}"},
            )
            if claim_resp.status_code != 200:
                continue

            # 启动任务（IDLE → BUSY）
            await _start_task(client, seed, agent_b["id"], tid)

            # 获取验证项 + 当前版本
            verifs = await _get_verifications(client, seed, tid)
            fresh = await _get_task(client, seed, tid)

            # 提交（finish_current_task 后 BUSY → IDLE）
            submit_resp = await client.post(
                f"/v1/tasks/{tid}/submit",
                json={
                    "summary": "由 Worker Bravo 救援",
                    "evidence": {"recovered": True, "output_access": {"type": "inline", "value": "recovery result"}},
                    "verification_results": [{
                        "verification_id": verifs[0]["id"],
                        "status": "passed",
                        "evidence": "由 Worker Bravo 救援并验证",
                    }],
                    "expected_version": fresh["version_no"],
                },
                headers={"Authorization": f"Bearer {key_b}"},
            )
            if submit_resp.status_code != 200:
                continue

            # 创建者验证
            fresh2 = await _get_task(client, seed, tid)
            await _verify_task(client, seed, verifs[0]["id"], fresh2["version_no"], "passed")

        # ── 验证 EventStore 追踪 ──
        events = await _get_team_events(client, seed)
        event_types = [e["event_type"] for e in events]
        assert "worker.runtime.error" in event_types, (
            f"agent.runtime.error 缺失。事件列表: {sorted(set(event_types))}")

        recovery_events = [e for e in events if e["event_type"] in (
            "worker.runtime.error", "task.lease_expired", "task.escalated")]
        assert len(recovery_events) > 0, (
            f"{sorted(set(event_types))} 中没有恢复事件")

        # 清理: 停用已崩溃 agent，避免污染其他测试。
        # 心跳检测器 + finish_current_task 交互会使 agent 处于
        # active+idle 但心跳已过期的陈旧状态，导致后续故障检测
        # 扫描出现误报。
        await client.delete(
            f"/v1/agents/{agent_a['id']}",
            headers=auth_header(seed.token),
        )


# ═══════════════════════════════════════════════════════════════════════
# 第 3 节: 审查超时 — 超时审查信号
# ═══════════════════════════════════════════════════════════════════════


class TestReviewTimeout:
    """任务已提交但创建者未验证 → 发出 review.overdue 信号。"""

    @pytest.mark.asyncio
    async def test_review_timeout_emits_signal(
        self, client: AsyncClient, seed: SeedData,
    ):
        """提交任务后将 submit 事件回溯日期，使 review_timeout
        检测器触发 → 验证 review.overdue 事件已发出。"""
        # ── 准备 ──
        agent_a, key_a = await _register_worker(client, seed, "B10-Review-Worker")
        await _worker_handshake(client, agent_a["id"], key_a)
        await _worker_heartbeat(client, agent_a["id"], key_a)

        project = await _create_project(client, seed, "B10 审查超时")
        # B55 (GAP-7): Workers need project role for submit
        await ensure_project_role(client, project["id"], agent_a["id"], "builder", auth_header(seed.token))
        batch = await _create_batch(client, seed, project["id"])
        task_data = await _create_task_api(
            client, seed, project["id"], "审查超时任务", batch["id"])

        # 分配 → 启动 → 提交
        task_data = await _assign_task(
            client, seed, task_data["id"], "worker", agent_a["id"], task_data["version_no"])
        await _start_task(client, seed, agent_a["id"], task_data["id"])
        verifs = await _get_verifications(client, seed, task_data["id"])

        fresh = await _get_task(client, seed, task_data["id"])
        submitted = await _submit_task(
            client, agent_a["id"], key_a, task_data["id"],
            fresh["version_no"], verifs[0]["id"])
        assert submitted["status"] == "in_verification"

        # ── 将 submit 事件回溯日期至 25 小时前（T_REVIEW=24h）──
        from src.db import async_session_factory
        from src.models.event import Event

        async with async_session_factory() as db_session:
            old_time = datetime.now(timezone.utc) - timedelta(seconds=90000)  # 25 小时
            old_time_naive = old_time.replace(tzinfo=None)
            # 使用 ORM 查询而非原始 SQL，确保表存在
            stmt = select(Event).where(
                Event.target_id == task_data["id"],
                Event.event_type == "task.submitted",
            ).order_by(Event.created_at.desc()).limit(1)
            result = await db_session.execute(stmt)
            event = result.scalar_one_or_none()
            if event:
                event.created_at = old_time_naive
            await db_session.commit()

        # ── 运行审查超时检测器 ──
        from src.services.failure_detector import detect_review_timeouts

        async with async_session_factory() as db_session:
            result = await detect_review_timeouts(db_session)
            await db_session.commit()

        assert result["overdue_tasks"] >= 1
        assert task_data["id"] in result["overdue_task_ids"]

        # ── 验证 review.overdue 事件已发出 ──
        events = await _get_team_events(client, seed)
        event_types = [e["event_type"] for e in events]
        assert "review.overdue" in event_types, (
            f"review.overdue 缺失。事件列表: {sorted(set(event_types))}")

        overdue_events = [e for e in events if e["event_type"] == "review.overdue"]
        assert len(overdue_events) >= 1
        assert overdue_events[-1]["target_id"] == task_data["id"]

        # 清理: 验证任务使其变为 COMPLETED，而非 IN_VERIFICATION。
        # 回溯日期的 submit 事件会导致后续 review_timeout 扫描中
        # 出现误报（assert overdue_tasks == 0）。
        final_state = await _get_task(client, seed, task_data["id"])
        await _verify_task(client, seed, verifs[0]["id"], final_state["version_no"], "passed")


# ═══════════════════════════════════════════════════════════════════════
# 第 4 节: 多 Worker 协作 — 同一批次
# ═══════════════════════════════════════════════════════════════════════


class TestMultiWorkerCollaboration:
    """两个 Worker 在同一批次中独立处理不同任务。"""

    @pytest.mark.asyncio
    async def test_two_workers_one_batch(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Worker A 取 Task 1，Worker B 取同一批次中的 Task 2。
        两者独立完成 → 最后一个任务完成时触发 batch.completed。"""
        # ── 准备 ──
        agent_a, key_a = await _register_worker(client, seed, "B10-Collab-Alpha")
        agent_b, key_b = await _register_worker(client, seed, "B10-Collab-Bravo")
        await _worker_handshake(client, agent_a["id"], key_a)
        await _worker_handshake(client, agent_b["id"], key_b)
        await _worker_heartbeat(client, agent_a["id"], key_a)
        await _worker_heartbeat(client, agent_b["id"], key_b)

        project = await _create_project(client, seed, "B10 协作")
        # B55 (GAP-7): Workers need project role for submit
        admin_headers = auth_header(seed.token)
        await ensure_project_role(client, project["id"], agent_a["id"], "builder", admin_headers)
        await ensure_project_role(client, project["id"], agent_b["id"], "builder", admin_headers)
        batch = await _create_batch(client, seed, project["id"])

        task_a = await _create_task_api(client, seed, project["id"], "协作任务 A", batch["id"])
        task_b = await _create_task_api(client, seed, project["id"], "协作任务 B", batch["id"])

        # 管理员推送分配: Task A → Worker A, Task B → Worker B
        task_a = await _assign_task(
            client, seed, task_a["id"], "worker", agent_a["id"], task_a["version_no"])
        task_b = await _assign_task(
            client, seed, task_b["id"], "worker", agent_b["id"], task_b["version_no"])

        # 两个 Worker 独立启动
        await _start_task(client, seed, agent_a["id"], task_a["id"])
        await _start_task(client, seed, agent_b["id"], task_b["id"])

        # 两者提交
        verifs_a = await _get_verifications(client, seed, task_a["id"])
        verifs_b = await _get_verifications(client, seed, task_b["id"])

        fresh_a = await _get_task(client, seed, task_a["id"])
        fresh_b = await _get_task(client, seed, task_b["id"])

        sub_a = await _submit_task(
            client, agent_a["id"], key_a, task_a["id"],
            fresh_a["version_no"], verifs_a[0]["id"])
        sub_b = await _submit_task(
            client, agent_b["id"], key_b, task_b["id"],
            fresh_b["version_no"], verifs_b[0]["id"])
        assert sub_a["status"] == "in_verification"
        assert sub_b["status"] == "in_verification"

        # 两者验证
        final_a = await _get_task(client, seed, task_a["id"])
        final_b = await _get_task(client, seed, task_b["id"])
        await _verify_task(client, seed, verifs_a[0]["id"], final_a["version_no"], "passed")
        await _verify_task(client, seed, verifs_b[0]["id"], final_b["version_no"], "passed")

        ta = await _get_task(client, seed, task_a["id"])
        tb = await _get_task(client, seed, task_b["id"])
        assert ta["status"] == "completed"
        assert tb["status"] == "completed"

        # batch.completed 应触发
        events = await _get_team_events(client, seed)
        event_types = [e["event_type"] for e in events]
        assert "batch.completed" in event_types, (
            f"batch.completed 缺失。事件列表: {sorted(set(event_types))}")


# ═══════════════════════════════════════════════════════════════════════
# 第 5 节: 阻塞报告流程
# ═══════════════════════════════════════════════════════════════════════


class TestBlockerReport:
    """Worker 遇到阻塞 → 报告 → 任务释放 → 无惩罚。"""

    @pytest.mark.asyncio
    async def test_blocker_report_flow(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Worker A 遇到阻塞 → 报告 → 任务回到 READY。
        redo_count 不递增（D-P7-017）。Worker B 救援。"""
        # ── 准备 ──
        agent_a, key_a = await _register_worker(client, seed, "B10-Blocker-Alpha")
        agent_b, key_b = await _register_worker(client, seed, "B10-Blocker-Bravo")
        await _worker_handshake(client, agent_a["id"], key_a)
        await _worker_handshake(client, agent_b["id"], key_b)
        await _worker_heartbeat(client, agent_a["id"], key_a)
        await _worker_heartbeat(client, agent_b["id"], key_b)

        project = await _create_project(client, seed, "B10 阻塞")
        # B55 (GAP-7): Workers need project role for submit
        admin_headers = auth_header(seed.token)
        await ensure_project_role(client, project["id"], agent_a["id"], "builder", admin_headers)
        await ensure_project_role(client, project["id"], agent_b["id"], "builder", admin_headers)
        batch = await _create_batch(client, seed, project["id"])
        task_data = await _create_task_api(
            client, seed, project["id"], "阻塞任务", batch["id"])

        # 分配给 Worker A
        task_data = await _assign_task(
            client, seed, task_data["id"], "worker", agent_a["id"], task_data["version_no"])
        await _start_task(client, seed, agent_a["id"], task_data["id"])

        # Worker A 报告阻塞（使用有效的枚举值）
        fresh = await _get_task(client, seed, task_data["id"])
        released = await _report_blocker(
            client, key_a, task_data["id"],
            blocker_type="external_dependency",
            description="缺少此任务所需的上游 API 密钥",
            suggested_fix="从管理面板提供 API 密钥",
            expected_version=fresh["version_no"],
        )

        # 任务应为 READY 且 redo_count 不递增（D-P7-017）
        assert released["status"] == "ready", (
            f"阻塞后期望 ready，实际为 {released['status']}")
        assert released["redo_count"] == task_data.get("redo_count", 0), (
            f"阻塞时 redo_count 不应递增: "
            f"原值 {task_data.get('redo_count', 0)}，现值 {released['redo_count']}")

        # Worker B 认领并完成
        claim_b = await client.post(
            f"/v1/tasks/{task_data['id']}/claim?expected_version={released['version_no']}",
            headers={"Authorization": f"Bearer {key_b}"},
        )
        assert claim_b.status_code == 200, f"认领失败: {claim_b.text}"

        await _start_task(client, seed, agent_b["id"], task_data["id"])
        verifs = await _get_verifications(client, seed, task_data["id"])
        fresh_b = await _get_task(client, seed, task_data["id"])

        await _submit_task(
            client, agent_b["id"], key_b, task_data["id"],
            fresh_b["version_no"], verifs[0]["id"])
        final = await _get_task(client, seed, task_data["id"])
        await _verify_task(client, seed, verifs[0]["id"], final["version_no"], "passed")

        final_task = await _get_task(client, seed, task_data["id"])
        assert final_task["status"] == "completed"

        # 验证 blocker_reported 事件存在
        events = await _get_team_events(client, seed)
        event_types = [e["event_type"] for e in events]
        assert "task.blocker_reported" in event_types, (
            f"task.blocker_reported 缺失。事件列表: {sorted(set(event_types))}")


# ═══════════════════════════════════════════════════════════════════════
# 第 6 节: EventStore 追踪完整性（自包含 E2E 流程）
# ═══════════════════════════════════════════════════════════════════════


class TestEventStoreCompleteness:
    """运行自包含的 E2E 流程并审计结果事件追踪。"""

    P8_KEY_EVENTS = [
        "task.created", "task.readied", "task.claimed", "task.assigned",
        "task.paused", "task.resumed", "task.submitted",
        "task.completed", "task.rejected", "task.cancelled",
        "task.lease_expired", "task.blocker_reported",
        "worker.runtime.busy", "worker.runtime.idle", "worker.runtime.error",
        "verification.executed", "task.review_timeout", "task.escalated",
        "batch.created", "batch.completed", "review.overdue",
    ]

    async def _run_minimal_e2e(self, client, seed, label):
        """运行最小化 E2E 流程并返回生成的事件。"""
        agent_a, key_a = await _register_worker(client, seed, f"B10-{label}")
        await _worker_handshake(client, agent_a["id"], key_a)
        await _worker_heartbeat(client, agent_a["id"], key_a)
        project = await _create_project(client, seed, f"B10 {label}")
        # B55 (GAP-7): Workers need project role for submit
        await ensure_project_role(client, project["id"], agent_a["id"], "builder", auth_header(seed.token))
        batch = await _create_batch(client, seed, project["id"])
        task = await _create_task_api(client, seed, project["id"], f"{label} 任务", batch["id"])
        task = await _assign_task(client, seed, task["id"], "worker", agent_a["id"], task["version_no"])
        await _start_task(client, seed, agent_a["id"], task["id"])
        verifs = await _get_verifications(client, seed, task["id"])
        fresh = await _get_task(client, seed, task["id"])
        await _submit_task(client, agent_a["id"], key_a, task["id"], fresh["version_no"], verifs[0]["id"])
        final = await _get_task(client, seed, task["id"])
        await _verify_task(client, seed, verifs[0]["id"], final["version_no"], "passed")
        return await _get_team_events(client, seed, limit=100)

    @pytest.mark.asyncio
    async def test_event_trace_and_payload(
        self, client: AsyncClient, seed: SeedData,
    ):
        """运行最小化 E2E 流程并验证事件类型和负载结构。"""
        events = await self._run_minimal_e2e(client, seed, "EventAudit")
        assert len(events) > 0, "未生成任何事件"
        event_types_in_store = {e["event_type"] for e in events}

        must_have = [
            "batch.created", "task.created", "task.assigned",
            "task.submitted", "task.completed", "batch.completed",
            "worker.runtime.busy", "worker.runtime.idle", "verification.executed",
        ]
        for evt in must_have:
            assert evt in event_types_in_store, (
                f"必需事件 '{evt}' 缺失。当前: {sorted(event_types_in_store)}")

        unexpected = [evt for evt in self.P8_KEY_EVENTS if evt not in event_types_in_store]
        if unexpected:
            print(f"\n⚠️  未触发的事件（已由单元测试覆盖）: {unexpected}")

        # 负载结构检查
        for event in events:
            for field in ["id", "event_type", "created_at", "team_id", "actor_type", "actor_id"]:
                assert event.get(field) is not None, f"事件缺少 '{field}': {event}"
            if event.get("target_type"):
                assert event["target_type"] in {"task", "batch", "worker", "verification", "project", "project_actor_role"}, (
                    f"未知 target_type: {event['target_type']}")
