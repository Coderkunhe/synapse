"""E2E 测试: 任务流程 — 创建、分配、认领、提交、验证、取消。"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ensure_project_role, ready_task


def _uniq_slug(prefix: str) -> str:
    """生成唯一的项目 slug。"""
    from src.utils.id_gen import generate_id
    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestTaskHappyPath:
    """完整任务生命周期: backlog → in_progress → in_verification → completed。"""

    @pytest.mark.asyncio
    async def test_full_task_lifecycle(self, client: AsyncClient, seed: SeedData):
        """完整快乐路径，包含 2 个验证项，均通过。"""
        headers = auth_header(seed.token)

        # ── 准备: project + agent ──
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Test Project", "slug": _uniq_slug("test")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Build Bot", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        # 握手以激活
        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [{"name": "coding", "description": "编写代码"}],
                "supported_events": ["task.assigned"],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )

        # ── 赋予 Worker builder 项目角色（B55 GAP-7: submit 需要 builder 权限）──
        await client.post(
            f"/v1/admin/projects/{project_id}/roles",
            json={"worker_id": agent_id, "role": "builder"},
            headers=headers,
        )

        # ── 创建任务（backlog）──
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "实现登录页面",
                "description": "构建包含邮箱 + 密码的登录表单",
                "priority": "p1",
                "verifications": [
                    {"type": "manual", "description": "登录功能正常",
                     "criteria": {"url": "/login", "expected_status": 200}},
                    {"type": "check_list", "description": "Code quality checks pass",
                     "criteria": {"lint": "pass", "tests": "pass"}},
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task = task_resp.json()
        assert task["status"] == "backlog"
        task_id = task["id"]

        # P11-B72: promote to ready before assign
        task = await ready_task(client, task, seed.token)
        version = task["version_no"]

        # 单独获取验证项（不在 TaskResponse 中）
        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        assert ver_resp.status_code == 200
        verifications = ver_resp.json()
        assert len(verifications) == 2
        ver_ids = [v["id"] for v in verifications]

        # ── 分配任务 → in_progress ──
        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        assert assign_resp.status_code == 200, assign_resp.text
        task = assign_resp.json()
        assert task["status"] == "in_progress"
        assert task["owner_type"] == "worker"
        assert task["owner_id"] == agent_id
        version = task["version_no"]

        # ── Worker 提交 → in_verification ──
        submit_resp = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={
                "summary": "已实现登录页面",
                "evidence": {"commit": "abc123", "files_changed": 3, "output_access": {"type": "git_branch", "value": "https://github.com/test/repo@feature/login"}},
                "verification_results": [
                    {"verification_id": ver_ids[0], "status": "passed", "evidence": "自检通过"},
                    {"verification_id": ver_ids[1], "status": "passed", "evidence": "自检通过"},
                ],
                "expected_version": version,
            },
            headers=auth_header(api_key),
        )
        assert submit_resp.status_code == 200, submit_resp.text
        assert submit_resp.json()["status"] == "in_verification"
        version = submit_resp.json()["version_no"]

        # ── 验证两项 → completed ──
        for vid in ver_ids:
            verify_resp = await client.post(
                f"/v1/verifications/{vid}/verify",
                json={"status": "passed", "comment": "看起来不错", "expected_task_version": version},
                headers=headers,
            )
            assert verify_resp.status_code == 200, f"验证 {vid}: {verify_resp.status_code} {verify_resp.text}"

        # 全部通过后，任务应为 completed
        final_resp = await client.get(f"/v1/tasks/{task_id}", headers=headers)
        assert final_resp.status_code == 200
        assert final_resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_task_events_recorded(self, client: AsyncClient, seed: SeedData):
        """验证任务操作会记录事件。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Event Project", "slug": _uniq_slug("event")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 创建任务 → 应记录 task.created
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "事件测试任务",
                "description": "Verify task works correctly",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "Verify all checks passed", "criteria": {}}],
            },
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        # 取消 → 应记录 task.cancelled
        cancel_resp = await client.post(
            f"/v1/tasks/{task_id}/cancel",
            params={"expected_version": version},
            headers=headers,
        )
        assert cancel_resp.status_code == 200

        # 检查团队事件
        events_resp = await client.get(
            f"/v1/teams/{seed.team_id}/events",
            headers=headers,
        )
        assert events_resp.status_code == 200
        events = events_resp.json()["items"]
        event_types = [e["event_type"] for e in events]
        assert "task.created" in event_types
        assert "task.cancelled" in event_types


class TestAgentClaimFlow:
    """Worker 自助服务: 查找可用任务 → 认领。"""

    @pytest.mark.asyncio
    async def test_agent_claim_task(self, client: AsyncClient, seed: SeedData):
        """Worker 查找可用任务并认领一个。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "认领项目", "slug": _uniq_slug("claim")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 注册 + 握手 agent
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "认领者", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0.0",
                "capabilities": [{"name": "coding", "description": "编码"}],
                "supported_events": ["task.assigned"],
                "preferred_channel": "websocket",
            },
            headers=auth_header(api_key),
        )

        # B56: claim requires builder project role
        await ensure_project_role(
            client, project_id, agent_id, "builder", headers,
        )

        # 创建任务，然后通过 DB 播种为 "ready"（无 API 端点可移动到 ready）
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "可认领任务",
                "description": "Verify task works correctly",
                "priority": "p1",
                "verifications": [{"type": "manual", "description": "Verification check passed", "criteria": {}}],
            },
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        from src.db import async_session_factory
        from src.models.task import Task
        async with async_session_factory() as session:
            task = await session.get(Task, task_id)
            task.status = "ready"
            task.version += 1  # 直接 DB 变更时递增版本
            version = task.version
            await session.commit()

        # Worker 查看可用任务
        avail_resp = await client.get(
            f"/v1/projects/{project_id}/tasks/available",
            headers=auth_header(api_key),
        )
        assert avail_resp.status_code == 200
        assert len(avail_resp.json()["items"]) == 1

        # Worker 认领
        claim_resp = await client.post(
            f"/v1/tasks/{task_id}/claim",
            params={"expected_version": version},
            headers=auth_header(api_key),
        )
        assert claim_resp.status_code == 200
        task = claim_resp.json()
        assert task["status"] == "in_progress"
        assert task["owner_type"] == "worker"
        assert task["owner_id"] == agent_id


class TestTaskCancelFlow:
    """从不同状态取消任务。"""

    @pytest.mark.asyncio
    async def test_cancel_from_backlog(self, client: AsyncClient, seed: SeedData):
        """Backlog 任务可以取消。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "取消项目", "slug": _uniq_slug("cancel")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "可取消任务",
                "description": "Verify task works correctly",
                "priority": "p3",
                "verifications": [{"type": "manual", "description": "Verify all checks passed", "criteria": {}}],
            },
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]
        assert task_resp.json()["status"] == "backlog"

        cancel_resp = await client.post(
            f"/v1/tasks/{task_id}/cancel",
            params={"expected_version": version},
            headers=headers,
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_fails(self, client: AsyncClient, seed: SeedData):
        """已完成任务不能取消（非法转换）。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "不可取消项目", "slug": _uniq_slug("nocancel")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        # 创建任务 + agent + 完成流程
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "完成者", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": [],
                  "supported_events": [], "preferred_channel": "websocket"},
            headers=auth_header(api_key),
        )

        # B55 (GAP-7): submit requires builder project role
        await client.post(
            f"/v1/admin/projects/{project_id}/roles",
            json={"worker_id": agent_id, "role": "builder"},
            headers=headers,
        )

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "将被完成",
                "description": "Verify task works correctly",
                "priority": "p3",
                "verifications": [{"type": "manual", "description": "Verification check passed", "criteria": {}}],
            },
            headers=headers,
        )
        task_id = task_resp.json()["id"]

        # P11-B72: promote to ready before assign
        task = await ready_task(client, task_resp.json(), seed.token)
        version = task["version_no"]

        # 获取验证项 ID
        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        # 分配
        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign_resp.json()["version_no"]

        # 提交
        submit_resp = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "完成",
                  "evidence": {"output_access": {"type": "inline", "value": "test"}},
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}],
                  "expected_version": version},
            headers=auth_header(api_key),
        )
        version = submit_resp.json()["version_no"]

        # 验证（完成任务）
        await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )

        # 重新读取以获取当前版本
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        version = task["version_no"]

        # 现在尝试取消 → 应失败
        cancel_resp = await client.post(
            f"/v1/tasks/{task_id}/cancel",
            params={"expected_version": version},
            headers=headers,
        )
        assert cancel_resp.status_code == 400
        assert cancel_resp.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


class TestVerificationRework:
    """验证失败 → REJECTED → start_task → IN_PROGRESS → 重新提交（P8-B5）。"""

    @pytest.mark.asyncio
    async def test_verification_failure_returns_to_in_progress(
        self, client: AsyncClient, seed: SeedData
    ):
        """验证失败应将任务设为 REJECTED；Worker 重新启动回到 IN_PROGRESS。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "返工项目", "slug": _uniq_slug("rework")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "返工者", "provider": "claude", "provider_model": "sonnet"},
            headers=headers,
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": [],
                  "supported_events": [], "preferred_channel": "websocket"},
            headers=auth_header(api_key),
        )

        # B55 (GAP-7): submit requires builder project role
        await client.post(
            f"/v1/admin/projects/{project_id}/roles",
            json={"worker_id": agent_id, "role": "builder"},
            headers=headers,
        )

        # 创建任务
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "需要返工",
                "description": "Verify task works correctly",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "Quality gate passed successfully",
                                   "criteria": {}}],
            },
            headers=headers,
        )
        task_id = task_resp.json()["id"]

        # P11-B72: promote to ready before assign
        task = await ready_task(client, task_resp.json(), seed.token)
        version = task["version_no"]

        # 获取验证项 ID
        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        # 分配
        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign_resp.json()["version_no"]

        # 提交
        submit_resp = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "第一次尝试",
                  "evidence": {"output_access": {"type": "inline", "value": "test"}},
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}],
                  "expected_version": version},
            headers=auth_header(api_key),
        )
        version = submit_resp.json()["version_no"]

        # 验证失败 → REJECTED（P8-B5: 使用状态机，而非直接 IN_PROGRESS）
        fail_resp = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "failed", "comment": "需要更多测试",
                  "rejection_reason": "测试覆盖不足",
                  "expected_task_version": version},
            headers=headers,
        )
        assert fail_resp.status_code == 200

        # 任务应为 REJECTED（不是 IN_PROGRESS — P8-B5 状态机）
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "rejected"
        assert task["redo_count"] == 1
        version = task["version_no"]

        # Worker 重新启动被拒绝的任务 → IN_PROGRESS（P8-B5）
        start_resp = await client.post(
            f"/v1/agents/{agent_id}/start-task?task_id={task_id}",
            headers=auth_header(api_key),
        )
        assert start_resp.status_code == 200
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "in_progress"
        version = task["version_no"]

        # 重新提交
        submit2_resp = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "已修复，添加了更多测试",
                  "evidence": {"output_access": {"type": "inline", "value": "test"}},
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}],
                  "expected_version": version},
            headers=auth_header(api_key),
        )
        version = submit2_resp.json()["version_no"]

        # 验证通过
        await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )

        # 现在已完成
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "completed"
        assert task["redo_count"] == 1  # redo_count 从第一次拒绝保留


class TestAdminWorkerAuth:
    """P11-B15 + B55 (GAP-7): Admin Worker 应能通过 API key 执行全角色操作。

    验证 require_permission 守卫正确支持 Worker actor（PFL-034 + PFL-039）。
    Admin 角色通过 ROLE_HIERARCHY 继承 orchestrator + builder + steward，
    因此单个 admin Worker 可以完成 assign + submit + verify 全链路。
    B55 之前此测试用 orchestrator 角色也能 submit，仅因 submit_task 当时无 guard。
    """

    @pytest.mark.asyncio
    async def test_admin_worker_can_assign_submit_and_verify(
        self, client: AsyncClient, seed: SeedData
    ):
        """Admin Worker (API key auth) 执行 assign + submit + verify 全链路。

        P11-B72: 使用独立的 Builder agent 执行 Task，Admin agent 负责验收。
        职责分离 — Manual 类型 verification 的 verifier 不能是 task owner。
        """
        admin_headers = auth_header(seed.token)

        # ── 1. 创建 Project ──
        slug = _uniq_slug("p11-b15")
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "P11-B15 Test", "slug": slug},
            headers=admin_headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        # ── 2. 注册 Orchestrator Worker Agent ──
        orch_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Orch Test", "provider": "claude", "provider_model": "sonnet"},
            headers=admin_headers,
        )
        assert orch_resp.status_code == 201, orch_resp.text
        orch_id = orch_resp.json()["worker"]["id"]
        orch_api_key = orch_resp.json()["api_key"]
        orch_headers = auth_header(orch_api_key)

        # Handshake 激活
        hs_resp = await client.post(
            f"/v1/agents/{orch_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": ["orchestrate"], "preferred_channel": "websocket"},
            headers=orch_headers,
        )
        assert hs_resp.status_code == 200, hs_resp.text

        # ── 3. 注册 Builder Worker Agent（P11-B72: 独立执行者）──
        builder_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Builder Test", "provider": "claude", "provider_model": "sonnet"},
            headers=admin_headers,
        )
        assert builder_resp.status_code == 201, builder_resp.text
        builder_id = builder_resp.json()["worker"]["id"]
        builder_api_key = builder_resp.json()["api_key"]
        builder_headers = auth_header(builder_api_key)

        await client.post(
            f"/v1/agents/{builder_id}/handshake",
            json={"worker_version": "1.0.0", "capabilities": ["coding"], "preferred_channel": "websocket"},
            headers=builder_headers,
        )

        # ── 4. 赋予角色 ──
        # B55 (GAP-7): admin inherits orchestrator + builder + steward via ROLE_HIERARCHY
        role_resp = await client.post(
            f"/v1/admin/projects/{project_id}/roles",
            json={"worker_id": orch_id, "role": "admin"},
            headers=admin_headers,
        )
        assert role_resp.status_code == 201, role_resp.text

        # Builder needs builder role for submit
        await client.post(
            f"/v1/admin/projects/{project_id}/roles",
            json={"worker_id": builder_id, "role": "builder"},
            headers=admin_headers,
        )

        # ── 5. 创建 Task（带 verification 条件）──
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "P11-B15: Assign + Verify 权限测试",
                "description": "验证 Orchestrator 能用 API key 执行核心操作",
                "priority": "p2",
                "verifications": [
                    {"type": "manual", "description": "Manual confirmation passed", "criteria": {"check": "所有检查通过"}}
                ],
            },
            headers=admin_headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]
        task_version = task_resp.json()["version_no"]

        # P11-B72: promote to ready before assign
        task = await ready_task(client, task_resp.json(), seed.token)
        task_version = task["version_no"]

        # ── 6. TEST: Orchestrator API key 分配 Task 给 Builder → 200 ──
        assign_resp = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": builder_id, "expected_version": task_version},
            headers=orch_headers,
        )
        assert assign_resp.status_code == 200, (
            f"PFL-034: Orchestrator assign 应返回 200，实际 {assign_resp.status_code}: {assign_resp.text}"
        )
        task_version = assign_resp.json()["version_no"]

        # ── 7. Builder 提交 ──
        ver_id = task_resp.json().get("verifications", [{}])[0].get("id")
        if not ver_id:
            ver_list = await client.get(f"/v1/tasks/{task_id}/verifications", headers=admin_headers)
            ver_id = ver_list.json()[0]["id"]

        submit_resp = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={
                "summary": "已完成",
                "evidence": {"output_access": {"type": "inline", "value": "completed task output"}},
                "verification_results": [
                    {"verification_id": ver_id, "status": "passed", "evidence": "自检通过"}
                ],
                "expected_version": task_version,
            },
            headers=builder_headers,
        )
        assert submit_resp.status_code == 200, submit_resp.text
        task_version = submit_resp.json()["version_no"]

        # ── 8. TEST: Orchestrator API key 验收 → 200（verifier ≠ task owner ✅）──
        verify_resp = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "approved", "comment": "Orchestrator 验收通过", "expected_task_version": task_version},
            headers=orch_headers,
        )
        assert verify_resp.status_code == 200, (
            f"PFL-039: Orchestrator verify 应返回 200，实际 {verify_resp.status_code}: {verify_resp.text}"
        )

        # 验证 Task 状态流转到 completed
        final_resp = await client.get(f"/v1/tasks/{task_id}", headers=admin_headers)
        assert final_resp.json()["status"] == "completed"


class TestProjectResolve:
    """P9-B1: Project resolve-by-name — Task 入口放松的基石。"""

    @pytest.mark.asyncio
    async def test_resolve_creates_project(self, client: AsyncClient, seed: SeedData):
        """首次 resolve 应自动创建 Project。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            "/v1/projects/resolve?name=MyProject",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        project = resp.json()
        assert project["name"] == "MyProject"
        assert project["team_id"] == seed.team_id
        assert project["status"] == "active"
        assert project["id"].startswith("prj_")

    @pytest.mark.asyncio
    async def test_resolve_returns_existing(self, client: AsyncClient, seed: SeedData):
        """重复 resolve 同一 name 应返回已有 Project，不重复创建。"""
        headers = auth_header(seed.token)

        # 第一次
        r1 = await client.post(
            "/v1/projects/resolve?name=DupProject",
            headers=headers,
        )
        assert r1.status_code == 200
        pid1 = r1.json()["id"]

        # 第二次
        r2 = await client.post(
            "/v1/projects/resolve?name=DupProject",
            headers=headers,
        )
        assert r2.status_code == 200
        pid2 = r2.json()["id"]

        # 同一 ID
        assert pid1 == pid2

    @pytest.mark.asyncio
    async def test_create_task_via_resolved_project(self, client: AsyncClient, seed: SeedData):
        """通过 resolve 获取 Project → 创建 Task — P9-B1 核心闭环。"""
        headers = auth_header(seed.token)

        # 不预先创建 Project，直接用 resolve
        proj_resp = await client.post(
            "/v1/projects/resolve?name=MyProject",
            headers=headers,
        )
        assert proj_resp.status_code == 200
        project_id = proj_resp.json()["id"]

        # 用解析出的 project_id 创建 Task
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "通过 resolve 创建的任务",
                "description": "Verify task works correctly",
                "priority": "p2",
                "verifications": [{"type": "manual", "description": "All features work correctly"}],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task = task_resp.json()
        assert task["status"] == "backlog"
        assert task["title"] == "通过 resolve 创建的任务"

    @pytest.mark.asyncio
    async def test_resolve_missing_name_422(self, client: AsyncClient, seed: SeedData):
        """缺少 name 参数应返回 422。"""
        headers = auth_header(seed.token)
        resp = await client.post(
            "/v1/projects/resolve",
            headers=headers,
        )
        assert resp.status_code == 422
