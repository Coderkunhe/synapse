"""E2E 测试: Bootstrap endpoint — Worker 一键就绪。

覆盖: 鉴权 (API key + project_key), format=sh 脚本生成,
format=json AI 自举, 客户端类型处理 (claude/codex/cursor)。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


async def _create_worker_and_key(
    seed: SeedData, name: str = "Bootstrap Test Worker"
) -> tuple[str, str]:
    """Helper: create a worker with a known API key directly in DB.

    Returns (worker_id, api_key). The worker is created in PENDING status
    so it can handshake/bootstrap.
    """
    import hashlib
    import secrets

    from src.db import async_session_factory
    from src.models.worker import Worker
    from src.constants import WorkerActorType, WorkerStatus
    from src.utils.id_gen import generate_id

    worker_id = generate_id("worker")

    raw_key = f"sk-syn-{secrets.token_hex(32)}.{worker_id.replace('wor_', '')[-8:]}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    async with async_session_factory() as session:
        worker = Worker(
            id=worker_id,
            name=name,
            team_id=seed.team_id,
            actor_type=WorkerActorType.AGENT,
            provider="claude",
            provider_model="claude-sonnet-5",
            status=WorkerStatus.PENDING,
            api_key_hash=key_hash,
        )
        session.add(worker)
        await session.commit()

    return worker_id, raw_key


async def _create_project(seed: SeedData) -> str:
    """Helper: create a project and return its ID."""
    from src.db import async_session_factory
    from src.models.project import Project
    from src.utils.id_gen import generate_id

    project_id = generate_id("project")
    slug = f"test-{project_id.replace('prj_', '')[-8:]}"

    async with async_session_factory() as session:
        proj = Project(
            id=project_id,
            team_id=seed.team_id,
            name="Bootstrap Test Project",
            slug=slug,
            description="Project for bootstrap E2E tests",
        )
        session.add(proj)
        await session.commit()

    return project_id


# ═══════════════════════════════════════════════════════════════════
# Auth tests
# ═══════════════════════════════════════════════════════════════════


class TestBootstrapAuth:
    """Authentication tests for GET /v1/bootstrap."""

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(
        self, client: AsyncClient, seed: SeedData
    ):
        """No Authorization header → 401."""
        resp = await client.get(
            "/v1/bootstrap?worker_id=wa_fake&project_id=prj_fake"
        )
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(
        self, client: AsyncClient, seed: SeedData
    ):
        """Wrong API key → 401."""
        headers = auth_header("sk-syn-badkey0000000000000000000000000000000000000000000000000000000000.00000000")
        resp = await client.get(
            "/v1/bootstrap?worker_id=wa_fake&project_id=prj_fake",
            headers=headers,
        )
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_valid_worker_returns_200(
        self, client: AsyncClient, seed: SeedData
    ):
        """Valid API key + worker → 200 + shell script."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert "text/plain" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_wrong_worker_id_returns_401(
        self, client: AsyncClient, seed: SeedData
    ):
        """API key belongs to worker A, but worker_id says B → 401."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id=wa_wrong0000000&project_id={project_id}",
            headers=headers,
        )
        assert resp.status_code == 401, resp.text


# ═══════════════════════════════════════════════════════════════════
# format=sh tests
# ═══════════════════════════════════════════════════════════════════


class TestBootstrapShell:
    """Shell script output validation."""

    @pytest.mark.asyncio
    async def test_script_is_valid_bash_syntax(
        self, client: AsyncClient, seed: SeedData
    ):
        """Script passes bash -n (syntax check)."""
        import subprocess
        import tempfile

        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        script = resp.text

        # Write to temp file and run bash -n
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as f:
            f.write(script)
            tmp_path = f.name

        try:
            result = subprocess.run(
                ["bash", "-n", tmp_path], capture_output=True, text=True
            )
            assert result.returncode == 0, (
                f"bash -n failed:\n{result.stderr}"
            )
        finally:
            import os
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_script_contains_config_vars(
        self, client: AsyncClient, seed: SeedData
    ):
        """Script embeds API URL, worker ID, project ID, API key."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        script = resp.text

        assert worker_id in script
        assert project_id in script
        assert api_key in script
        assert "SYNAPSE_API_URL" in script
        assert "detect_client" in script
        assert "write_skill" in script
        assert "test_connection" in script
        assert "do_handshake" in script

    @pytest.mark.asyncio
    async def test_script_contains_skill_md_content(
        self, client: AsyncClient, seed: SeedData
    ):
        """Script embeds the SKILL.md template content."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        script = resp.text

        # Key phrases from SKILL.md that should be in the heredoc
        assert "Synapse Worker" in script
        assert "角色围栏" in script


# ═══════════════════════════════════════════════════════════════════
# format=json tests
# ═══════════════════════════════════════════════════════════════════


class TestBootstrapJson:
    """JSON manifest output validation."""

    @pytest.mark.asyncio
    async def test_json_returns_manifest_structure(
        self, client: AsyncClient, seed: SeedData
    ):
        """format=json returns {files, next_steps, worker_id, ...}."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}&format=json",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["worker_id"] == worker_id
        assert data["project_id"] == project_id
        assert data["client"] == "claude"  # default
        assert "files" in data
        assert isinstance(data["files"], dict)
        assert len(data["files"]) >= 1
        assert "next_steps" in data
        assert isinstance(data["next_steps"], list)
        assert "handshake_url" in data

    @pytest.mark.asyncio
    async def test_json_claude_has_correct_paths(
        self, client: AsyncClient, seed: SeedData
    ):
        """Claude client writes to .claude/skills/synapse/."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&format=json&client=claude",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert ".claude/skills/synapse/SKILL.md" in data["files"]
        assert ".claude/.env" in data["files"]
        assert "Synapse Worker" in data["files"][".claude/skills/synapse/SKILL.md"]

    @pytest.mark.asyncio
    async def test_json_codex_has_correct_paths(
        self, client: AsyncClient, seed: SeedData
    ):
        """Codex client writes to .agents/skills/synapse/."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&format=json&client=codex",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert ".agents/skills/synapse/SKILL.md" in data["files"]

    @pytest.mark.asyncio
    async def test_json_cursor_has_correct_paths(
        self, client: AsyncClient, seed: SeedData
    ):
        """Cursor client writes to .cursor/rules/ with alwaysApply."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&format=json&client=cursor",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert ".cursor/rules/synapse-worker.mdc" in data["files"]
        mdc_content = data["files"][".cursor/rules/synapse-worker.mdc"]
        assert "alwaysApply: true" in mdc_content
        assert "name:" not in mdc_content.split("---")[1]  # no name field

    @pytest.mark.asyncio
    async def test_json_invalid_client_returns_422(
        self, client: AsyncClient, seed: SeedData
    ):
        """Invalid client param → 422."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&format=json&client=vim",
            headers=headers,
        )
        assert resp.status_code == 422, resp.text


# ═══════════════════════════════════════════════════════════════════
# Client type handling in shell mode
# ═══════════════════════════════════════════════════════════════════


class TestBootstrapClientTypes:
    """Client-specific output validation."""

    @pytest.mark.asyncio
    async def test_explicit_claude_client(
        self, client: AsyncClient, seed: SeedData
    ):
        """client=claude → script writes .claude/ paths."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&client=claude",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        script = resp.text
        assert ".claude/skills/synapse" in script

    @pytest.mark.asyncio
    async def test_explicit_codex_client(
        self, client: AsyncClient, seed: SeedData
    ):
        """client=codex → script writes .agents/ paths."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&client=codex",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        script = resp.text
        assert ".agents/skills/synapse" in script

    @pytest.mark.asyncio
    async def test_explicit_cursor_client(
        self, client: AsyncClient, seed: SeedData
    ):
        """client=cursor → script writes .cursor/ paths + alwaysApply."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&client=cursor",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        script = resp.text
        assert ".cursor/rules" in script
        assert "synapse-worker.mdc" in script
        assert "alwaysApply: true" in script

    @pytest.mark.asyncio
    async def test_invalid_client_param_returns_422(
        self, client: AsyncClient, seed: SeedData
    ):
        """Invalid client → 422 validation error."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&client=emacs",
            headers=headers,
        )
        assert resp.status_code == 422, resp.text


# ═══════════════════════════════════════════════════════════════════
# Role handling
# ═══════════════════════════════════════════════════════════════════


class TestBootstrapRole:
    """Role parameter handling."""

    @pytest.mark.asyncio
    async def test_role_embedded_in_script(
        self, client: AsyncClient, seed: SeedData
    ):
        """Role parameter is embedded in the generated script."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&role=builder",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        script = resp.text
        assert 'SYNAPSE_ROLE="builder"' in script

    @pytest.mark.asyncio
    async def test_role_embedded_in_json(
        self, client: AsyncClient, seed: SeedData
    ):
        """Role parameter is in JSON manifest."""
        worker_id, api_key = await _create_worker_and_key(seed)
        project_id = await _create_project(seed)
        headers = auth_header(api_key)

        resp = await client.get(
            f"/v1/bootstrap?worker_id={worker_id}&project_id={project_id}"
            f"&role=orchestrator&format=json",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["role"] == "orchestrator"
