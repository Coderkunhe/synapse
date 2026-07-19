"""P9-B24 E2E Verification — Worker lifecycle integration test.

Tests the full B20-B23 chain: register → protocol → handshake → heartbeat.

Requires a running Synapse server. Skip gracefully if server is not available.
Run: .venv/bin/pytest tests/test_p9_b24_e2e.py -v
"""

import os
import re
import subprocess
import tempfile

import httpx
import pytest

BASE = "http://localhost:8000"


def _server_available() -> bool:
    """Check if the Synapse dev server is running."""
    try:
        r = httpx.get(f"{BASE}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# Module-level skip — all tests in this file require a running server
pytestmark = pytest.mark.skipif(
    not _server_available(),
    reason="Synapse dev server not running on localhost:8000",
)
TEAM_ID = "tea_019f3c7f4a9c7940"
PROJECT_ID = "prj_019f3c7f4aa0711e"


@pytest.fixture(scope="module")
def admin_token():
    """Generate admin JWT for the seed member."""
    import sys
    sys.path.insert(0, ".")
    from src.auth import create_access_token
    return create_access_token(
        user_id="github_hunter",
        member_id="mem_019f3c7f4a9e7709",
        team_id=TEAM_ID,
        role="admin",
    )


@pytest.fixture(scope="module")
def registered_agent(admin_token):
    """Register a test Worker and return (agent_id, api_key, data)."""
    with httpx.Client() as client:
        resp = client.post(
            f"{BASE}/v1/teams/{TEAM_ID}/agents",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "B24 E2E Test Worker",
                "worker_type": "agent",
                "provider": "claude",
                "role": "builder",
                "provider_model": "claude-sonnet-5",
            },
        )
    assert resp.status_code == 201, f"Register failed: {resp.status_code} {resp.text}"
    data = resp.json()
    agent_id = data["worker"]["id"]
    api_key = data["api_key"]
    return agent_id, api_key, data


class TestStep1_AgentRegistration:
    """Step 1: Worker registration → verify key format."""

    def test_api_key_prefix_correct(self, registered_agent):
        agent_id, api_key, data = registered_agent
        assert api_key.startswith("sk-syn-"), f"API key prefix wrong: {api_key[:20]}"

    def test_api_key_format_sk_syn_64hex_8chars(self, registered_agent):
        agent_id, api_key, data = registered_agent
        body = api_key[len("sk-syn-"):]
        hex_part, suffix = body.split(".")
        assert len(hex_part) == 64, f"Hex part length: {len(hex_part)}"
        agent_prefix = agent_id.replace("ag_", "")[:8]
        assert suffix == agent_prefix, f"Suffix: {suffix} vs agent prefix: {agent_prefix}"

    def test_agent_status_pending(self, registered_agent):
        _, _, data = registered_agent
        assert data["worker"]["status"] == "pending"


class TestStep2_SkillGeneration:
    """Step 2: generate-skill.sh --client → verify output."""

    def test_skill_files_exist(self):
        skill_dir = tempfile.mkdtemp(prefix="synapse-b24-")
        result = subprocess.run(
            ["bash", "tools/generate-skill.sh", "--client", "--output", skill_dir],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"generate-skill.sh failed: {result.stderr}"
        assert os.path.isfile(f"{skill_dir}/.claude/skills/synapse/SKILL.md")
        assert os.path.isfile(f"{skill_dir}/.claude/skills/synapse/_env.md")

    def test_no_unfilled_placeholders(self):
        skill_dir = tempfile.mkdtemp(prefix="synapse-b24-")
        subprocess.run(
            ["bash", "tools/generate-skill.sh", "--client", "--output", skill_dir],
            capture_output=True,
        )
        content = open(f"{skill_dir}/.claude/skills/synapse/SKILL.md").read()
        unfilled = re.findall(r'\{\{[A-Z_][A-Z_]*\}\}', content)
        assert len(unfilled) == 0, f"Unfilled placeholders: {unfilled}"


class TestStep3_ProtocolAPI:
    """Step 3: GET /agents/{id}/protocol → verify 4-field response."""

    @pytest.fixture(scope="class")
    def protocol_response(self, registered_agent):
        agent_id, api_key, _ = registered_agent
        with httpx.Client() as client:
            resp = client.get(
                f"{BASE}/v1/agents/{agent_id}/protocol?project_id={PROJECT_ID}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        assert resp.status_code == 200, f"Protocol failed: {resp.status_code} {resp.text}"
        return resp.json()

    def test_has_project_context(self, protocol_response):
        assert protocol_response.get("project_context"), "project_context empty/missing"

    def test_has_collaboration_norms(self, protocol_response):
        assert protocol_response.get("collaboration_norms"), "collaboration_norms empty/missing"

    def test_has_role_instructions(self, protocol_response):
        assert protocol_response.get("role_instructions"), "role_instructions empty/missing"

    def test_has_env_template(self, protocol_response):
        assert protocol_response.get("env_template"), "env_template empty/missing"


class TestStep4_Handshake:
    """Step 4: POST /agents/{id}/handshake → verify status transition."""

    @pytest.fixture(scope="class")
    def handshake_response(self, registered_agent):
        agent_id, api_key, _ = registered_agent
        with httpx.Client() as client:
            resp = client.post(
                f"{BASE}/v1/agents/{agent_id}/handshake",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "worker_version": "1.0.0",
                    "capabilities": [{"name": "code_gen", "description": "Generate code"}],
                    "supported_events": ["task.assigned"],
                    "preferred_channel": "websocket",
                },
            )
        assert resp.status_code == 200, f"Handshake failed: {resp.status_code} {resp.text}"
        return resp.json()

    def test_status_active(self, handshake_response):
        assert handshake_response["status"] == "active"


class TestStep5_Heartbeat:
    """Step 5: POST /agents/{id}/heartbeat → verify keepalive."""

    @pytest.fixture(scope="class")
    def heartbeat_response(self, registered_agent):
        agent_id, api_key, _ = registered_agent
        with httpx.Client() as client:
            resp = client.post(
                f"{BASE}/v1/agents/{agent_id}/heartbeat",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"current_load": 0},
            )
        assert resp.status_code == 200, f"Heartbeat failed: {resp.status_code} {resp.text}"
        return resp.json()

    def test_status_ok(self, heartbeat_response):
        assert heartbeat_response["status"] == "ok"

    def test_has_runtime_status(self, heartbeat_response):
        assert "runtime_status" in heartbeat_response
