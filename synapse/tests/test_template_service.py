"""Tests for template_service.py — B21 template rendering engine + protocol API."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.services.template_service import (
    load_template,
    render,
    render_protocol,
    resolve_role,
    resolve_variables,
    VALID_ROLES,
)

# Import SeedData for type hints
from tests.conftest import SeedData, auth_header


# ── Unit: render ────────────────────────────────────────────────────


class TestRender:
    def test_replaces_all_vars(self):
        result, unfilled = render(
            "Hello {{NAME}}, your role is {{ROLE}}.",
            {"NAME": "Alice", "ROLE": "builder"},
        )
        assert result == "Hello Alice, your role is builder."
        assert unfilled == []

    def test_detects_unfilled(self):
        result, unfilled = render(
            "{{A}} {{B}} {{C}}",
            {"A": "1"},
        )
        assert result == "1 {{B}} {{C}}"
        assert unfilled == ["B", "C"]

    def test_no_vars_returns_unchanged(self):
        result, unfilled = render("plain text", {})
        assert result == "plain text"
        assert unfilled == []

    def test_none_value_treated_as_unfilled(self):
        result, unfilled = render("{{X}}", {"X": None})
        assert result == "{{X}}"
        assert unfilled == ["X"]

    def test_empty_string_treated_as_filled(self):
        """Empty string is a valid value — means 'no notes' or 'not set'."""
        result, unfilled = render("{{X}}", {"X": ""})
        assert result == ""
        assert unfilled == []

    def test_partial_fill_mixed(self):
        result, unfilled = render(
            "Project: {{PROJECT_NAME}}\nPhase: {{CURRENT_PHASE}}\nStack: {{FRONTEND_STACK}}",
            {"PROJECT_NAME": "Synapse", "CURRENT_PHASE": "P9"},
        )
        assert "Project: Synapse" in result
        assert "Phase: P9" in result
        assert "{{FRONTEND_STACK}}" in result
        assert unfilled == ["FRONTEND_STACK"]


# ── Unit: load_template ─────────────────────────────────────────────


class TestLoadTemplate:
    def test_loads_existing_template(self):
        """_common.md has been superseded by _protocol.md (P11-B2)."""
        content = load_template("_protocol.md")
        assert "平台协议" in content
        assert "{{YOUR_ROLE}}" in content

    def test_missing_template_raises(self):
        with pytest.raises(FileNotFoundError):
            load_template("nonexistent.md")

    def test_all_template_files_loadable(self):
        for name in [
            "_common.md",
            "_env.md",
            "_project.md",
            "_protocol.md",
            "_task-current.md",
            "role-orchestrator.md",
            "role-builder.md",
            "role-steward.md",
        ]:
            content = load_template(name)
            assert len(content) > 0, f"{name} is empty"


# ── Unit: resolve_role ──────────────────────────────────────────────


class TestResolveRole:
    def test_query_param_wins(self, _make_agent):
        agent = _make_agent(metadata={"role": "steward"})
        role, source = resolve_role(agent, "orchestrator")
        assert role == "orchestrator"
        assert source == "query_param"

    def test_falls_back_to_metadata(self, _make_agent):
        agent = _make_agent(metadata={"role": "steward"})
        role, source = resolve_role(agent)
        assert role == "steward"
        assert source == "worker_metadata"

    def test_defaults_to_builder(self, _make_agent):
        agent = _make_agent(metadata={})
        role, source = resolve_role(agent)
        assert role == "builder"
        assert source == "default_fallback"

    def test_invalid_query_param_ignored(self, _make_agent):
        agent = _make_agent(metadata={"role": "orchestrator"})
        role, source = resolve_role(agent, "admin")
        assert role == "orchestrator"
        assert source == "worker_metadata"

    def test_invalid_metadata_role_ignored(self, _make_agent):
        agent = _make_agent(metadata={"role": "intern"})
        role, source = resolve_role(agent)
        assert role == "builder"
        assert source == "default_fallback"


# ── Unit: resolve_variables ─────────────────────────────────────────


class TestResolveVariables:
    @pytest.mark.asyncio
    async def test_config_sourced_vars(self, _make_agent, _make_project):
        agent = _make_agent()
        project = _make_project(name="TestProj")
        vars_ = await resolve_variables(
            agent, project, "builder",
            api_base_url="https://api.example.com",
            heartbeat_interval=30,
        )
        assert vars_["SYNAPSE_API_URL"] == "https://api.example.com"
        assert vars_["SYNAPSE_HEARTBEAT_INTERVAL"] == "30"

    @pytest.mark.asyncio
    async def test_agent_sourced_vars(self, _make_agent, _make_project):
        agent = _make_agent()
        project = _make_project()
        vars_ = await resolve_variables(agent, project, "orchestrator")
        assert vars_["SYNAPSE_WORKER_ID"] == agent.id
        assert vars_["YOUR_ROLE"] == "orchestrator"

    @pytest.mark.asyncio
    async def test_project_direct_fields(self, _make_agent, _make_project):
        project = _make_project(
            name="Atlas",
            description="Mapping platform",
            git_repo_url="https://github.com/org/atlas",
        )
        agent = _make_agent()
        vars_ = await resolve_variables(agent, project, "builder")
        assert vars_["PROJECT_NAME"] == "Atlas"
        assert vars_["PROJECT_DESCRIPTION"] == "Mapping platform"
        assert vars_["GIT_REPO_URL"] == "https://github.com/org/atlas"
        assert vars_["SYNAPSE_PROJECT_ID"] == project.id

    @pytest.mark.asyncio
    async def test_project_metadata_fallback(self, _make_agent, _make_project):
        project = _make_project(
            metadata_='{"frontend_stack": "React", "backend_stack": "FastAPI", "database": "PostgreSQL"}'
        )
        agent = _make_agent()
        vars_ = await resolve_variables(agent, project, "builder")
        assert vars_["FRONTEND_STACK"] == "React"
        assert vars_["BACKEND_STACK"] == "FastAPI"
        assert vars_["DATABASE"] == "PostgreSQL"

    @pytest.mark.asyncio
    async def test_api_key_not_in_variables(self, _make_agent, _make_project):
        agent = _make_agent()
        project = _make_project()
        vars_ = await resolve_variables(agent, project, "builder")
        assert "SYNAPSE_API_KEY" not in vars_


# ── Integration: render_protocol ────────────────────────────────────


class TestRenderProtocol:
    @pytest.mark.asyncio
    async def test_returns_all_five_sections(self, _make_agent, _make_project):
        agent = _make_agent()
        project = _make_project(name="TestProject")
        result = await render_protocol(agent, project, "builder")
        assert "project_context" in result
        assert "collaboration_norms" in result
        assert "role_instructions" in result
        assert "env_template" in result
        assert "role_source" in result
        assert "unfilled_variables" in result

    @pytest.mark.asyncio
    async def test_project_name_rendered_in_output(self, _make_agent, _make_project):
        agent = _make_agent()
        project = _make_project(name="Helios")
        result = await render_protocol(agent, project, "builder")
        assert "Helios" in result["project_context"]
        assert "Helios" in result["collaboration_norms"]

    @pytest.mark.asyncio
    async def test_role_rendered_in_output(self, _make_agent, _make_project):
        agent = _make_agent()
        project = _make_project(name="P")
        result = await render_protocol(agent, project, "orchestrator")
        assert "orchestrator" in result["collaboration_norms"]
        assert "编排" in result["role_instructions"]  # orchestrator role content

    @pytest.mark.asyncio
    async def test_role_source_passed_through(self, _make_agent, _make_project):
        agent = _make_agent()
        project = _make_project(name="P")
        result = await render_protocol(agent, project, "builder", role_source="query_param")
        assert result["role_source"] == "query_param"

    @pytest.mark.asyncio
    async def test_task_vars_not_in_unfilled(self, _make_agent, _make_project):
        """_task-current.md is not yet rendered by render_protocol — Phase 2 feature."""
        agent = _make_agent()
        project = _make_project(name="P")
        result = await render_protocol(agent, project, "builder")
        # _task-current.md is NOT loaded — task-specific rendering is B24+
        task_vars = [v for v in result["unfilled_variables"] if v.startswith("TASK_")]
        assert len(task_vars) == 0  # not loaded yet

    @pytest.mark.asyncio
    async def test_no_unfilled_for_fully_configured_project(self, _make_agent, _make_project):
        """When project metadata has all the optional fields, only SYNAPSE_API_KEY unfilled."""
        import json
        project = _make_project(
            name="Complete",
            description="Full desc",
            git_repo_url="https://git.example.com/repo",
            metadata_=json.dumps({
                "frontend_stack": "React",
                "frontend_notes": "",
                "backend_stack": "FastAPI",
                "backend_notes": "",
                "database": "PostgreSQL",
                "database_notes": "",
                "deployment": "Docker",
                "deployment_notes": "",
                "current_phase": "P9",
                "active_batch": "B21",
                "current_priority": "High",
                "admin_name": "Admin",
                "orchestrator_worker_id": "ag_orch",
                "builder_worker_id": "ag_build",
                "steward_worker_id": "ag_steward",
                "docs_url": "https://docs.example.com",
                "ci_url": "https://ci.example.com",
                "project_conventions": "Use tabs",
            }),
        )
        agent = _make_agent()
        result = await render_protocol(agent, project, "builder")
        # SYNAPSE_API_KEY is deliberately excluded (secret); _task-current.md not loaded
        expected_unfilled = {"SYNAPSE_API_KEY"}
        actual = set(result["unfilled_variables"])
        assert actual == expected_unfilled, f"Expected {expected_unfilled}, got {actual}"


# ── Integration: API endpoint ───────────────────────────────────────


class TestProtocolEndpoint:
    @pytest.mark.asyncio
    async def test_returns_rendered_protocol(self, client: AsyncClient, seed: SeedData):
        """Full E2E: register agent → get protocol → verify content."""
        headers = auth_header(seed.token)
        slug = _uniq_slug("proto1")

        # Create project
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Protocol Test", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        # Register agent
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={
                "name": "ProtoBot",
                "provider": "claude",
                "provider_model": "sonnet",
                "metadata": {"role": "builder"},
            },
            headers=headers,
        )
        assert agent_resp.status_code == 201, agent_resp.text
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        # Handshake to activate
        hs_resp = await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert hs_resp.status_code == 200, hs_resp.text

        # Fetch protocol
        proto_resp = await client.get(
            f"/v1/agents/{agent_id}/protocol",
            params={"project_id": project_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert proto_resp.status_code == 200, proto_resp.text
        body = proto_resp.json()
        assert "project_context" in body
        assert "collaboration_norms" in body
        assert "role_instructions" in body
        assert "env_template" in body
        assert "unfilled_variables" in body
        assert "Protocol Test" in body["project_context"]
        assert body["role_instructions"]  # should be non-empty

    @pytest.mark.asyncio
    async def test_auth_required(self, client: AsyncClient, seed: SeedData):
        resp = await client.get(
            f"/v1/agents/nonexistent/protocol",
            params={"project_id": "prj_123"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cross_team_rejected(self, client: AsyncClient, seed: SeedData):
        """Worker cannot access project from a different team."""
        headers = auth_header(seed.token)

        # Register agent in seed's team
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "IsolatedBot", "provider": "claude"},
            headers=headers,
        )
        assert agent_resp.status_code == 201, agent_resp.text
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        # Activate
        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        # Create a SECOND team with its own project
        from src.auth import create_access_token
        from src.utils.id_gen import generate_id
        from src.db import async_session_factory

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team
            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(id=team2_id, name=f"Other Team {short}", slug=f"other-{short}")
            member2 = Member(
                id=member2_id, team_id=team2_id,
                user_id=f"user-{member2_id[:8]}", display_name="OtherAdmin", role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}", member_id=member2_id,
            team_id=team2_id, role="admin",
        )

        # Create project in team 2
        proj_resp = await client.post(
            f"/v1/teams/{team2_id}/projects",
            json={"name": "Other Project", "slug": _uniq_slug("cross")},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert proj_resp.status_code == 201, proj_resp.text
        other_project_id = proj_resp.json()["id"]

        # Worker from team 1 tries to access project from team 2
        resp = await client.get(
            f"/v1/agents/{agent_id}/protocol",
            params={"project_id": other_project_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403, resp.text

    @pytest.mark.asyncio
    async def test_role_from_metadata(self, client: AsyncClient, seed: SeedData):
        """Worker with role=steward in metadata gets steward instructions."""
        headers = auth_header(seed.token)
        slug = _uniq_slug("proto2")

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Guard Test", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={
                "name": "GuardBot",
                "provider": "claude",
                "metadata": {"role": "steward"},
            },
            headers=headers,
        )
        assert agent_resp.status_code == 201, agent_resp.text
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        # Activate
        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        proto_resp = await client.get(
            f"/v1/agents/{agent_id}/protocol",
            params={"project_id": project_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert proto_resp.status_code == 200, proto_resp.text
        body = proto_resp.json()
        # Guardian role content uses 守护 or 审查
        assert ("守护" in body["role_instructions"] or "审查" in body["role_instructions"])

    @pytest.mark.asyncio
    async def test_role_query_param_overrides(self, client: AsyncClient, seed: SeedData):
        """Query param ?role=orchestrator overrides metadata role=builder."""
        headers = auth_header(seed.token)
        slug = _uniq_slug("proto3")

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Override Test", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={
                "name": "FlexBot",
                "provider": "claude",
                "metadata": {"role": "builder"},
            },
            headers=headers,
        )
        assert agent_resp.status_code == 201, agent_resp.text
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        proto_resp = await client.get(
            f"/v1/agents/{agent_id}/protocol",
            params={"project_id": project_id, "role": "orchestrator"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert proto_resp.status_code == 200, proto_resp.text
        body = proto_resp.json()
        # Should contain orchestrator content, not builder
        assert "编排" in body["role_instructions"]

    @pytest.mark.asyncio
    async def test_project_not_found(self, client: AsyncClient, seed: SeedData):
        headers = auth_header(seed.token)
        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "LostBot", "provider": "claude"},
            headers=headers,
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        await client.post(
            f"/v1/agents/{agent_id}/handshake",
            json={
                "worker_version": "1.0",
                "capabilities": [],
                "supported_events": [],
                "preferred_channel": "websocket",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        resp = await client.get(
            f"/v1/agents/{agent_id}/protocol",
            params={"project_id": "prj_nonexistent"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_pending_agent_can_access(self, client: AsyncClient, seed: SeedData):
        """Worker in 'pending' status (not yet handshaked) can still fetch protocol."""
        headers = auth_header(seed.token)
        slug = _uniq_slug("proto4")

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Pending Test", "slug": slug},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        agent_resp = await client.post(
            f"/v1/teams/{seed.team_id}/agents",
            json={"name": "PendingBot", "provider": "claude"},
            headers=headers,
        )
        agent_id = agent_resp.json()["worker"]["id"]
        api_key = agent_resp.json()["api_key"]

        # No handshake — agent is still "pending"
        resp = await client.get(
            f"/v1/agents/{agent_id}/protocol",
            params={"project_id": project_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, resp.text


# ── Helpers ─────────────────────────────────────────────────────────

import json

def _uniq_slug(prefix: str) -> str:
    """Generate a unique slug for test project creation."""
    import uuid
    short = uuid.uuid4().hex[:8]
    return f"{prefix}-{short}"

class _FakeAgent:
    """Minimal fake for unit tests that don't need a real DB."""

    def __init__(self, *, id: str = "ag_test", metadata: dict | None = None):
        self.id = id
        self.metadata_ = json.dumps(metadata) if metadata is not None else None
        self.team = _FakeTeam()

class _FakeTeam:
    def __init__(self, *, name: str = "Test Team"):
        self.name = name

class _FakeProject:
    """Minimal fake for unit tests that don't need a real DB."""

    def __init__(
        self,
        *,
        id: str = "prj_test",
        name: str = "Test Project",
        description: str | None = None,
        git_repo_url: str | None = None,
        api_docs_url: str | None = None,
        metadata_: str | None = None,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.git_repo_url = git_repo_url
        self.api_docs_url = api_docs_url
        self.metadata_ = metadata_


@pytest.fixture
def _make_agent():
    def _make(*, id: str = "ag_test", metadata: dict | None = None):
        return _FakeAgent(id=id, metadata=metadata)
    return _make


@pytest.fixture
def _make_project():
    def _make(
        *,
        id: str = "prj_test",
        name: str = "Test Project",
        description: str | None = None,
        git_repo_url: str | None = None,
        api_docs_url: str | None = None,
        metadata_: str | None = None,
    ):
        return _FakeProject(
            id=id, name=name, description=description,
            git_repo_url=git_repo_url, api_docs_url=api_docs_url,
            metadata_=metadata_,
        )
    return _make
