"""P13-B8: Evidence 维度多 Worker 测试。

测试覆盖:
  - Evidence 提交验证: valid · null 拒绝 (PFL-143) · empty 拒绝
  - Provider evidence config 差异: structured vs free_text · 文件支持
  - Evidence submit → task status transition to in_verification

使用 B6 harness: _create_provisioned_worker + assertions。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header, ready_task
from tests.harness.fixtures import _create_provisioned_worker
from tests.harness.providers import (
    claude_code_provider_config,
    codex_cli_provider_config,
    custom_provider_config,
)


# ── Evidence Config 验证 ────────────────────────────────────────


class TestEvidenceConfigValidation:
    """evidence 维度 config 结构 + 差异验证。"""

    def test_claude_evidence_is_structured(self):
        cfg = claude_code_provider_config()["evidence"]
        assert cfg["format"] == "structured"
        assert cfg["supports_files"] is True
        assert cfg["supports_diff"] is True
        assert cfg["supports_screenshot"] is True

    def test_codex_evidence_is_free_text(self):
        cfg = codex_cli_provider_config()["evidence"]
        assert cfg["format"] == "free_text"
        assert cfg["supports_files"] is False
        assert cfg["supports_diff"] is False
        assert cfg["supports_screenshot"] is False

    def test_both_providers_have_same_max_size(self):
        """max_size_bytes 应一致（server 限制统一）。"""
        claude_max = claude_code_provider_config()["evidence"]["max_size_bytes"]
        codex_max = codex_cli_provider_config()["evidence"]["max_size_bytes"]
        assert claude_max == codex_max == 65536

    def test_claude_supports_all_evidence_types(self):
        cfg = claude_code_provider_config()["evidence"]
        assert cfg["supports_files"]
        assert cfg["supports_diff"]
        assert cfg["supports_screenshot"]

    def test_codex_supports_no_file_evidence(self):
        cfg = codex_cli_provider_config()["evidence"]
        assert not cfg["supports_files"]
        assert not cfg["supports_diff"]
        assert not cfg["supports_screenshot"]

    def test_custom_evidence_config(self):
        cfg = custom_provider_config(evidence={
            "format": "binary",
            "max_size_bytes": 128000,
        })
        assert cfg["evidence"]["format"] == "binary"
        assert cfg["evidence"]["max_size_bytes"] == 128000


# ── Evidence 提交验证 ───────────────────────────────────────────


class TestEvidenceSubmission:
    """evidence 提交 → task status 转换。"""

    @pytest.mark.asyncio
    async def test_submit_with_valid_structured_evidence(
        self, client: AsyncClient, seed: SeedData,
    ):
        """提交含结构化 evidence → 200 · task → in_verification。"""
        worker = await _create_provisioned_worker(
            client, seed, "Evidence-Worker", claude_code_provider_config(),
        )

        headers = auth_header(seed.token)
        create_resp = await client.post(
            f"/v1/projects/{worker['project_id']}/tasks",
            json={
                "title": "Evidence Task",
                "description": "Testing evidence submission with structured output_access",
                "priority": "p2",
                "verifications": [{
                    "type": "manual",
                    "description": "Verify evidence present in submission",
                }],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, f"Task create failed: {create_resp.text}"
        task = create_resp.json()
        task = await ready_task(client, task, seed.token)

        claim_resp = await client.post(
            f"/v1/tasks/{task['id']}/claim",
            json={"expected_version": task["version_no"]},
            headers=auth_header(worker["api_key"]),
        )
        assert claim_resp.status_code == 200
        version = claim_resp.json()["version_no"]

        # Submit with valid evidence including required output_access
        submit_resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Completed — all checks pass",
                "evidence": {
                    "output_access": {
                        "type": "git_branch",
                        "value": "https://github.com/example/repo@feature/fix",
                    },
                    "pr_url": "https://github.com/example/pr/1",
                    "commit_hash": "abc123def456",
                    "test_results": "827 tests passed",
                },
                "expected_version": version,
            },
            headers=auth_header(worker["api_key"]),
        )
        assert submit_resp.status_code == 200, (
            f"Submit failed: {submit_resp.status_code} {submit_resp.text}"
        )
        result = submit_resp.json()
        assert result["status"] == "in_verification", (
            f"Expected in_verification, got {result['status']}"
        )

    @pytest.mark.asyncio
    async def test_submit_with_free_text_evidence(
        self, client: AsyncClient, seed: SeedData,
    ):
        """Codex Worker 提交 free_text evidence → 200。"""
        worker = await _create_provisioned_worker(
            client, seed, "Codex-Evidence", codex_cli_provider_config(),
        )

        headers = auth_header(seed.token)
        create_resp = await client.post(
            f"/v1/projects/{worker['project_id']}/tasks",
            json={
                "title": "Codex Evidence Task",
                "description": "Testing free_text evidence from Codex Worker via inline output",
                "priority": "p2",
                "verifications": [{
                    "type": "manual",
                    "description": "Verify Codex free-text evidence submission",
                }],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, f"Task create: {create_resp.text}"
        task = create_resp.json()
        task = await ready_task(client, task, seed.token)

        claim_resp = await client.post(
            f"/v1/tasks/{task['id']}/claim",
            json={"expected_version": task["version_no"]},
            headers=auth_header(worker["api_key"]),
        )
        assert claim_resp.status_code == 200
        version = claim_resp.json()["version_no"]

        submit_resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Task completed successfully. Fixed the bug and added tests.",
                "evidence": {
                    "output_access": {
                        "type": "inline",
                        "value": "Build passed. All tests green.",
                    },
                },
                "expected_version": version,
            },
            headers=auth_header(worker["api_key"]),
        )
        assert submit_resp.status_code == 200, (
            f"Codex submit failed: {submit_resp.status_code} {submit_resp.text}"
        )
        assert submit_resp.json()["status"] == "in_verification"

    @pytest.mark.asyncio
    async def test_submit_null_evidence_rejected(
        self, client: AsyncClient, seed: SeedData,
    ):
        """PFL-143: null evidence → 422 (Pydantic validator at submit level)。"""
        worker = await _create_provisioned_worker(
            client, seed, "Null-Evidence", claude_code_provider_config(),
        )

        headers = auth_header(seed.token)
        create_resp = await client.post(
            f"/v1/projects/{worker['project_id']}/tasks",
            json={
                "title": "Null Evidence Task",
                "description": "Testing null evidence rejection at submit time",
                "priority": "p2",
                "verifications": [{
                    "type": "manual",
                    "description": "Check null evidence gets rejected by PFL-143 validator",
                }],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, f"Task create: {create_resp.text}"
        task = create_resp.json()
        task = await ready_task(client, task, seed.token)

        claim_resp = await client.post(
            f"/v1/tasks/{task['id']}/claim",
            json={"expected_version": task["version_no"]},
            headers=auth_header(worker["api_key"]),
        )
        assert claim_resp.status_code == 200
        version = claim_resp.json()["version_no"]

        submit_resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Done",
                "evidence": None,  # null evidence — PFL-143 rejects
                "expected_version": version,
            },
            headers=auth_header(worker["api_key"]),
        )
        assert submit_resp.status_code == 422, (
            f"Null evidence should be rejected, got {submit_resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_submit_empty_evidence_rejected(
        self, client: AsyncClient, seed: SeedData,
    ):
        """PFL-143: empty evidence dict → 422。"""
        worker = await _create_provisioned_worker(
            client, seed, "Empty-Evidence", claude_code_provider_config(),
        )

        headers = auth_header(seed.token)
        create_resp = await client.post(
            f"/v1/projects/{worker['project_id']}/tasks",
            json={
                "title": "Empty Evidence Task",
                "description": "Testing empty evidence dict rejection at submit time",
                "priority": "p2",
                "verifications": [{
                    "type": "manual",
                    "description": "Check empty evidence dict gets rejected by PFL-143",
                }],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, f"Task create: {create_resp.text}"
        task = create_resp.json()
        task = await ready_task(client, task, seed.token)

        claim_resp = await client.post(
            f"/v1/tasks/{task['id']}/claim",
            json={"expected_version": task["version_no"]},
            headers=auth_header(worker["api_key"]),
        )
        assert claim_resp.status_code == 200
        version = claim_resp.json()["version_no"]

        submit_resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Done",
                "evidence": {},  # empty dict
                "expected_version": version,
            },
            headers=auth_header(worker["api_key"]),
        )
        assert submit_resp.status_code == 422, (
            f"Empty evidence should be rejected, got {submit_resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_submit_without_output_access_rejected(
        self, client: AsyncClient, seed: SeedData,
    ):
        """evidence 缺少 output_access → 409 OUTPUT_ACCESS_REQUIRED。"""
        worker = await _create_provisioned_worker(
            client, seed, "NoOA-Worker", claude_code_provider_config(),
        )

        headers = auth_header(seed.token)
        create_resp = await client.post(
            f"/v1/projects/{worker['project_id']}/tasks",
            json={
                "title": "No OutputAccess Task",
                "description": "Testing evidence without output_access rejection",
                "priority": "p2",
                "verifications": [{
                    "type": "manual",
                    "description": "Check evidence missing output_access is rejected",
                }],
            },
            headers=headers,
        )
        assert create_resp.status_code == 201, f"Task create: {create_resp.text}"
        task = create_resp.json()
        task = await ready_task(client, task, seed.token)

        claim_resp = await client.post(
            f"/v1/tasks/{task['id']}/claim",
            json={"expected_version": task["version_no"]},
            headers=auth_header(worker["api_key"]),
        )
        assert claim_resp.status_code == 200
        version = claim_resp.json()["version_no"]

        submit_resp = await client.post(
            f"/v1/tasks/{task['id']}/submit",
            json={
                "summary": "Done",
                "evidence": {
                    "some_data": "present",
                    "but_missing": "output_access",
                },
                "expected_version": version,
            },
            headers=auth_header(worker["api_key"]),
        )
        assert submit_resp.status_code == 409, (
            f"Evidence without output_access should get 409, got {submit_resp.status_code}"
        )
        error = submit_resp.json()
        assert error["error"]["code"] == "OUTPUT_ACCESS_REQUIRED"
