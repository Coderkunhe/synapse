"""P8-B6: 批量验证 + 二级验证。

测试覆盖:
  - 批量全部通过 → 任务 COMPLETED
  - 批量混合结果（通过 + 失败）→ 任务 REJECTED
  - 批量带 review_flag → 任务保持 IN_VERIFICATION
  - auto_approved 标记记录在验证项上
  - 批量包含来自多个任务的条目
  - 批量错误情况（未找到、已执行、错误状态）
  - 单条验证带 review_flag（非批量路径）
"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ensure_project_role


def _uniq_slug(prefix: str) -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


async def _setup_agent_with_task(
    client: AsyncClient, seed: SeedData, project_name: str, slug_prefix: str,
    verifications: list[dict] | None = None,
):
    """辅助函数: 创建 project、agent、带验证项的任务，分配+提交。
    返回 (headers, agent_id, api_key, task_id, ver_ids, version)。
    """
    headers = auth_header(seed.token)

    proj_resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": project_name, "slug": _uniq_slug(slug_prefix)},
        headers=headers,
    )
    project_id = proj_resp.json()["id"]

    agent_resp = await client.post(
        f"/v1/teams/{seed.team_id}/agents",
        json={"name": f"Worker-{slug_prefix}", "provider": "claude", "provider_model": "sonnet"},
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

    # B55 (GAP-7): assign builder role for submit permission
    await ensure_project_role(client, project_id, agent_id, "builder", headers)

    if verifications is None:
        verifications = [{"type": "manual", "description": "Verify all checks passed"}]

    task_resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={"title": f"Task-{slug_prefix}", "description": "Verify task works correctly", "priority": "p2",
              "verifications": verifications},
        headers=headers,
    )
    task_id = task_resp.json()["id"]
    version = task_resp.json()["version_no"]

    ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
    ver_ids = [v["id"] for v in ver_resp.json()]

    # 分配
    assign = await client.post(
        f"/v1/tasks/{task_id}/assign",
        json={"owner_type": "worker", "owner_id": agent_id, "expected_version": version},
        headers=headers,
    )
    version = assign.json()["version_no"]

    # 提交并标记所有验证项为通过
    submit_payload = {
        "summary": "完成",
        "evidence": {"output_access": {"type": "inline", "value": "batch test output"}},
        "expected_version": version,
        "verification_results": [
            {"verification_id": vid, "status": "passed"} for vid in ver_ids
        ],
    }
    submit = await client.post(
        f"/v1/tasks/{task_id}/submit",
        json=submit_payload,
        headers=auth_header(api_key),
    )
    version = submit.json()["version_no"]

    return headers, agent_id, api_key, task_id, ver_ids, version


# ── 批量全部通过 ──────────────────────────────────────────────────


class TestBatchAllPass:
    """批量验证 — 全部通过 → 任务 COMPLETED。"""

    @pytest.mark.asyncio
    async def test_batch_all_pass_completes_tasks(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-AllPass", "b6ap",
            verifications=[
                {"type": "manual", "description": "Code review passed"},
                {"type": "automated", "description": "CI pipeline passes"},
            ],
        )

        # 批量验证两个
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "expected_task_version": version},
                    {"verification_id": ver_ids[1], "status": "passed",
                     "expected_task_version": version},
                ],
                "auto_approved": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["passed"] == 2
        assert data["summary"]["failed"] == 0
        assert data["summary"]["error"] == 0

        # 任务应为 COMPLETED
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "completed"

    @pytest.mark.asyncio
    async def test_batch_all_pass_single_verification(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-AP1", "b6ap1",
        )

        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "expected_task_version": version},
                ],
                "auto_approved": False,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["passed"] == 1

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "completed"


# ── 批量混合结果（通过 + 失败）───────────────────────────────────────


class TestBatchMixed:
    """混合结果的批量 → 任务 REJECTED。"""

    @pytest.mark.asyncio
    async def test_batch_mixed_pass_fail_rejects_task(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-Mix", "b6mix",
            verifications=[
                {"type": "manual", "description": "Verification condition one"},
                {"type": "manual", "description": "Verification condition two"},
            ],
        )

        # 第一个通过，第二个失败
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "expected_task_version": version},
                    {"verification_id": ver_ids[1], "status": "failed",
                     "rejection_reason": "不完整",
                     "expected_task_version": version},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["passed"] == 1
        assert data["summary"]["failed"] == 1

        # 任务应为 REJECTED
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "rejected"
        assert task["redo_count"] == 1

        # 检查任务结果
        outcomes = {o["task_id"]: o for o in data["task_outcomes"]}
        assert outcomes[task_id]["task_status"] == "rejected"


# ── 批量带 review_flag ──────────────────────────────────────────


class TestBatchReviewFlag:
    """批量带 review_flag → 任务保持 IN_VERIFICATION。"""

    @pytest.mark.asyncio
    async def test_batch_with_review_flag_keeps_task_in_verification(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-Flag", "b6flag",
            verifications=[
                {"type": "manual", "description": "Verification condition one"},
                {"type": "manual", "description": "Verification condition two"},
            ],
        )

        # 两个都通过但一个被标记
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "expected_task_version": version},
                    {"verification_id": ver_ids[1], "status": "passed",
                     "review_flag": True,
                     "expected_task_version": version},
                ],
                "auto_approved": True,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["passed"] == 1  # 第一个通过，第二个被标记
        assert data["summary"]["flagged"] == 1

        # 任务应仍为 IN_VERIFICATION（被标记的条目需要人工处理）
        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "in_verification"

        # 验证项应有 review_flag + auto_approved 设置
        # 被标记的验证项保持 "pending" 直到人工解决
        vers = (await client.get(
            f"/v1/tasks/{task_id}/verifications", headers=headers
        )).json()
        assert vers[0]["status"] == "passed"
        assert vers[0]["review_flag"] is False
        assert vers[1]["status"] == "pending"  # 被标记，未解决
        assert vers[1]["review_flag"] is True
        assert vers[1]["auto_approved"] is True
        # Claude 的建议存储在 evidence 中
        assert "claude_recommendation" in (vers[1]["evidence"] or {})

    @pytest.mark.asyncio
    async def test_flag_resolved_by_human_completes_task(
        self, client: AsyncClient, seed: SeedData
    ):
        """Claude 标记条目后，人工解决 → 任务完成。"""
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-Flag2", "b6flag2",
            verifications=[
                {"type": "manual", "description": "Verification condition one"},
            ],
        )

        # Claude 标记
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "review_flag": True,
                     "expected_task_version": version},
                ],
                "auto_approved": True,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["flagged"] == 1
        assert data["results"][0]["status"] == "flagged"

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "in_verification"  # 被标记，未解决
        version = task["version_no"]

        # 验证项应为 "pending" — 人工可通过单条验证解决
        vers = (await client.get(
            f"/v1/tasks/{task_id}/verifications", headers=headers
        )).json()
        assert vers[0]["status"] == "pending"
        assert vers[0]["review_flag"] is True

        # 人工解决标记（单条验证，无 review_flag）
        verify = await client.post(
            f"/v1/verifications/{ver_ids[0]}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )
        assert verify.status_code == 200

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "completed"


# ── auto_approved 记录 ─────────────────────────────────────────


class TestAutoApproved:
    """auto_approved 标记记录在验证项上。"""

    @pytest.mark.asyncio
    async def test_auto_approved_recorded_on_batch_verifications(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-Auto", "b6auto",
        )

        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "expected_task_version": version},
                ],
                "auto_approved": True,
            },
            headers=headers,
        )
        assert resp.status_code == 200

        vers = (await client.get(
            f"/v1/tasks/{task_id}/verifications", headers=headers
        )).json()
        assert vers[0]["auto_approved"] is True
        assert vers[0]["review_flag"] is False


# ── 跨多个任务的批量验证 ───────────────────────────────────────


class TestBatchMultiTask:
    """跨多个任务的批量验证。"""

    @pytest.mark.asyncio
    async def test_batch_across_two_tasks(
        self, client: AsyncClient, seed: SeedData
    ):
        # 任务 1
        h1, _, _, t1, v1_ids, v1 = await _setup_agent_with_task(
            client, seed, "B6-MT1", "b6mt1",
        )
        # 任务 2
        h2, _, _, t2, v2_ids, v2 = await _setup_agent_with_task(
            client, seed, "B6-MT2", "b6mt2",
        )

        headers = h1  # 同一团队，同一管理员

        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": v1_ids[0], "status": "passed",
                     "expected_task_version": v1},
                    {"verification_id": v2_ids[0], "status": "passed",
                     "expected_task_version": v2},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["passed"] == 2
        assert len(data["task_outcomes"]) == 2

        # 两个任务均完成
        t1_data = (await client.get(f"/v1/tasks/{t1}", headers=headers)).json()
        t2_data = (await client.get(f"/v1/tasks/{t2}", headers=headers)).json()
        assert t1_data["status"] == "completed"
        assert t2_data["status"] == "completed"


# ── 批量错误情况 ───────────────────────────────────────────────


class TestBatchErrors:
    """批量验证错误处理。"""

    @pytest.mark.asyncio
    async def test_batch_not_found_verification(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)

        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": "nonexistent-id", "status": "passed",
                     "expected_task_version": 1},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 200  # 批量本身成功
        data = resp.json()
        assert data["summary"]["error"] == 1
        assert data["results"][0]["status"] == "error"
        assert "not found" in data["results"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_batch_already_executed_verification(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-Dup", "b6dup",
        )

        # 第一次批量: 通过
        await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "expected_task_version": version},
                ],
            },
            headers=headers,
        )

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()

        # 第二次批量: 相同验证项 → 错误
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "failed",
                     "expected_task_version": task["version_no"]},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["error"] == 1
        assert "already executed" in data["results"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_batch_wrong_task_state(
        self, client: AsyncClient, seed: SeedData
    ):
        """验证一个尚未提交的任务（不在 IN_VERIFICATION 状态）。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "B6-State", "slug": _uniq_slug("b6state")},
            headers=headers,
        )
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={"title": "未提交", "description": "Verify task works correctly", "priority": "p2",
                  "verifications": [{"type": "manual", "description": "Verify all checks passed"}]},
            headers=headers,
        )
        task_id = task_resp.json()["id"]
        version = task_resp.json()["version_no"]

        ver_resp = await client.get(f"/v1/tasks/{task_id}/verifications", headers=headers)
        ver_id = ver_resp.json()[0]["id"]

        # 任务为 BACKLOG，不是 IN_VERIFICATION
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_id, "status": "passed",
                     "expected_task_version": version},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["error"] == 1
        assert "not in_verification" in data["results"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_batch_version_conflict(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, _, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-Ver", "b6ver",
        )

        # 错误版本 → 冲突
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": ver_ids[0], "status": "passed",
                     "expected_task_version": version + 999},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["error"] == 1
        assert "version" in data["results"][0]["error"].lower()


# ── 单条验证带 review_flag（非批量路径）─────────────────────────────────


class TestSingleVerifyReviewFlag:
    """单条验证带 review_flag。"""

    @pytest.mark.asyncio
    async def test_single_verify_with_review_flag(
        self, client: AsyncClient, seed: SeedData
    ):
        headers, _, api_key, task_id, ver_ids, version = await _setup_agent_with_task(
            client, seed, "B6-SFlag", "b6sflag",
        )

        # 测试单条验证路径不受新参数影响
        # （review_flag 和 auto_approved 有默认值，已有调用可正常工作）
        verify = await client.post(
            f"/v1/verifications/{ver_ids[0]}/verify",
            json={"status": "passed", "expected_task_version": version},
            headers=headers,
        )
        assert verify.status_code == 200
        data = verify.json()
        assert data["review_flag"] is False
        assert data["auto_approved"] is False

        task = (await client.get(f"/v1/tasks/{task_id}", headers=headers)).json()
        assert task["status"] == "completed"


# ── 批量空 / 验证 ────────────────────────────────────────


class TestBatchValidation:
    """批量端点的输入验证。"""

    @pytest.mark.asyncio
    async def test_batch_empty_items_rejected(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)
        resp = await client.post(
            "/v1/verifications/batch",
            json={"items": []},
            headers=headers,
        )
        assert resp.status_code == 422  # 验证错误

    @pytest.mark.asyncio
    async def test_batch_invalid_status_rejected(
        self, client: AsyncClient, seed: SeedData
    ):
        headers = auth_header(seed.token)
        resp = await client.post(
            "/v1/verifications/batch",
            json={
                "items": [
                    {"verification_id": "v-1", "status": "maybe",
                     "expected_task_version": 1},
                ],
            },
            headers=headers,
        )
        assert resp.status_code == 422
