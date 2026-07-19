"""P8-B5：Verification 状态机关联 — execute_verification 使用 apply_transition。

测试覆盖:
  - 单个 verification 通过 → COMPLETED
  - 多个 verification 全部通过 → COMPLETED
  - 单个 verification 失败 → REJECTED + redo_count
  - 多个 verification 混合结果 → REJECTED（未全部处理 → 保持 IN_VERIFICATION）
  - 多个 verification 全部失败 → REJECTED + redo_count
  - 结构化拒绝：rejection_reason 存储在 Verification 上
  - REJECTED → start_task → IN_PROGRESS → 重新提交 → 通过 → COMPLETED
  - redo_count 在多次拒绝中递增
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    """生成唯一 slug 用于测试隔离。"""
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


class TestSingleVerificationPass:
    """单个 verification 通过 → 任务 COMPLETED。"""

    @pytest.mark.asyncio
    async def test_single_verification_pass_completes_task(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-Single-Pass", "slug": _uniq_slug("vsp")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VSP", "provider": "claude", "provider_model": "sonnet"},
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

        # 创建带 1 个 verification 的任务
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Single verif pass", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Code review"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        # Assign → submit → verify pass
        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        submit = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Done", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit.json()["version_no"]

        verify = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )
        assert verify.status_code == 200

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "completed"
        assert task["redo_count"] == 0
        assert task["completed_at"] is not None


class TestMultiVerificationPass:
    """多个 verification 全部通过 → 任务 COMPLETED。"""

    @pytest.mark.asyncio
    async def test_multi_verification_all_pass_completes_task(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-Multi-Pass", "slug": _uniq_slug("vmp")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VMP", "provider": "claude", "provider_model": "sonnet"},
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

        # 创建带 2 个 verification 的任务
        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Multi verif pass", "description": "test", "priority": "p2",
                  "verifications": [
                      {"type": "manual", "description": "Code review"},
                      {"type": "automated", "description": "CI passes"},
                  ]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_ids = [v["id"] for v in ver_resp.json()]
        assert len(ver_ids) == 2

        # Assign → submit
        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        submit = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Done", "expected_version": version,
                  "verification_results": [
                      {"verification_id": ver_ids[0], "status": "passed"},
                      {"verification_id": ver_ids[1], "status": "passed"},
                  ]},
            headers=auth_header(api_key),
        )
        version = submit.json()["version_no"]

        # 验证两个 — 第一个不应完成任务（第二个仍待处理）
        v1 = await client.post(
            f"/v1/verifications/{ver_ids[0]}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )
        assert v1.status_code == 200
        task_mid = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task_mid["status"] == "in_verification"  # 仍在等待第二个
        version = task_mid["version_no"]

        # 验证第二个 → 现在 COMPLETED
        v2 = await client.post(
            f"/v1/verifications/{ver_ids[1]}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )
        assert v2.status_code == 200
        task_final = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task_final["status"] == "completed"
        assert task_final["redo_count"] == 0


class TestVerificationReject:
    """验证失败 → REJECTED + redo_count 递增。"""

    @pytest.mark.asyncio
    async def test_single_verification_fail_rejects_task(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-Fail", "slug": _uniq_slug("vfail")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VF", "provider": "claude", "provider_model": "sonnet"},
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

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Fail me", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Check"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        submit = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Done", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit.json()["version_no"]

        # 验证 FAILED，带结构化拒绝原因
        verify = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "failed", "rejection_reason": "Missing edge case tests",
                  "expected_task_version": version},
            headers=headers,
        )
        assert verify.status_code == 200

        # 任务应为 REJECTED 且 redo_count=1
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "rejected"
        assert task["redo_count"] == 1

        # Verification 应有 rejection_reason
        ver_detail = (await client.get(
            f"/v1/tasks/{task_id}/verifications", headers=headers
        )).json()
        assert ver_detail[0]["rejection_reason"] == "Missing edge case tests"


class TestRedoCountIncrement:
    """redo_count 在每次拒绝时递增。"""

    @pytest.mark.asyncio
    async def test_redo_count_increments_on_multiple_rejections(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-Redo", "slug": _uniq_slug("vredo")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VR", "provider": "claude", "provider_model": "sonnet"},
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

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Redo test", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Check"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        # 第 1 轮：submit → reject → start_task → redo_count=1
        submit1 = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Attempt 1", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit1.json()["version_no"]

        await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "failed", "rejection_reason": "Not good enough #1",
                  "expected_task_version": version},
            headers=headers,
        )
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["redo_count"] == 1
        version = task["version_no"]

        # 重新开始 → 重新提交
        await client.post(
            f"/v1/agents/{agent_id}/start-task?task_id={task_id}",
            headers=auth_header(api_key),
        )
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        version = task["version_no"]

        submit2 = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Attempt 2", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit2.json()["version_no"]

        # 第 2 轮：再次拒绝 → redo_count=2
        await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "failed", "rejection_reason": "Still not good enough #2",
                  "expected_task_version": version},
            headers=headers,
        )
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["redo_count"] == 2
        assert task["status"] == "rejected"


class TestRejectedToInProgressTransition:
    """start_task 通过状态机将 REJECTED → IN_PROGRESS。"""

    @pytest.mark.asyncio
    async def test_rejected_start_task_transitions_to_in_progress(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-R2I", "slug": _uniq_slug("vr2i")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VR2I", "provider": "claude", "provider_model": "sonnet"},
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

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "R2I test", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Check"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        submit = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Done", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit.json()["version_no"]

        # 拒绝
        await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "failed", "rejection_reason": "Bad",
                  "expected_task_version": version},
            headers=headers,
        )
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "rejected"

        # start_task 将 REJECTED → IN_PROGRESS
        start = await client.post(
            f"/v1/agents/{agent_id}/start-task?task_id={task_id}",
            headers=auth_header(api_key),
        )
        assert start.status_code == 200
        assert start.json()["active_task_id"] == task_id

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "in_progress"


class TestStructuredRejection:
    """rejection_reason 按 verification 存储，重新提交时清除。"""

    @pytest.mark.asyncio
    async def test_rejection_reason_cleared_on_resubmit(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-Clear", "slug": _uniq_slug("vclear")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VC", "provider": "claude", "provider_model": "sonnet"},
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

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Clear test", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Check"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        # 第 1 轮：submit → reject（带原因）
        submit1 = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Attempt 1", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit1.json()["version_no"]

        await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "failed", "rejection_reason": "Needs more tests",
                  "expected_task_version": version},
            headers=headers,
        )

        ver_after_reject = (await client.get(
            f"/v1/tasks/{task_id}/verifications", headers=headers
        )).json()
        assert ver_after_reject[0]["rejection_reason"] == "Needs more tests"

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        version = task["version_no"]

        # 重新开始 → 重新提交（rejection_reason 应被清除）
        await client.post(
            f"/v1/agents/{agent_id}/start-task?task_id={task_id}",
            headers=auth_header(api_key),
        )
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        version = task["version_no"]

        submit2 = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Attempt 2", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit2.json()["version_no"]

        # 验证通过
        await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )

        ver_after_pass = (await client.get(
            f"/v1/tasks/{task_id}/verifications", headers=headers
        )).json()
        assert ver_after_pass[0]["rejection_reason"] is None
        assert ver_after_pass[0]["status"] == "passed"


class TestEdgeCases:
    """Verification 状态机边界情况测试。"""

    @pytest.mark.asyncio
    async def test_verify_already_executed_verification_fails(
        self, client: AsyncClient, seed: SeedData
    ):
        """对已执行的 verification 再次 verify → 409。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-Dup", "slug": _uniq_slug("vdup")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VD", "provider": "claude", "provider_model": "sonnet"},
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

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Dup verify", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Check"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        submit = await client.post(
            f"/v1/tasks/{task_id}/submit",
            json={"summary": "Done", "expected_version": version,
                  "verification_results": [{"verification_id": ver_id, "status": "passed"}]},
            headers=auth_header(api_key),
        )
        version = submit.json()["version_no"]

        # 第一次 verify：通过
        v1 = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )
        assert v1.status_code == 200

        # 第二次 verify：已执行 → 409
        task2 = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        v2 = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "failed", "expected_task_version": task2["version_no"]},
            headers=headers,
        )
        assert v2.status_code == 409

    @pytest.mark.asyncio
    async def test_verify_task_not_in_verification_fails(
        self, client: AsyncClient, seed: SeedData
    ):
        """任务不在 IN_VERIFICATION 状态时 verify → 400。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-NotReady", "slug": _uniq_slug("vnr")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Not submitted yet", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Check"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        # 尝试 verify 仍在 BACKLOG 的任务 → 应失败
        v = await client.post(
            f"/v1/verifications/{ver_id}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )
        assert v.status_code == 400  # InvalidStateTransition → 400

    @pytest.mark.asyncio
    async def test_start_task_on_non_rejected_task_is_idempotent(
        self, client: AsyncClient, seed: SeedData
    ):
        """对 IN_PROGRESS 任务执行 start_task 应仅设置 agent 状态（无任务转换）。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "V-Idem", "slug": _uniq_slug("videm")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "Worker-VI", "provider": "claude", "provider_model": "sonnet"},
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

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "Idempotent start", "description": "test", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Check"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        assign = await client.post(
            f"/v1/tasks/{task_id}/assign",
            json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
            headers=headers,
        )
        version = assign.json()["version_no"]

        # 任务为 IN_PROGRESS — start_task 对任务状态应为空操作
        start = await client.post(
            f"/v1/agents/{agent_id}/start-task?task_id={task_id}",
            headers=auth_header(api_key),
        )
        assert start.status_code == 200
        assert start.json()["active_task_id"] == task_id

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "in_progress"  # 未变
