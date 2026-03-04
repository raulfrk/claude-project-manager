"""MCP tool tests for agents feature (proj_set_agent, proj_get_agents, proj_remove_agent, proj_resolve_agent)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.agents import STEP_DEFAULTS
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectMeta,
    RepoEntry,
)
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def agents_app(cfg: ProjConfig) -> Any:
    """Return a FastMCP app with agents tools registered."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import agents, config, projects

    app = FastMCP("test-agents")
    config.register(app)
    projects.register(app)
    agents.register(app)
    return app


@pytest.fixture()
def project_with_repo(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str, Path]:
    """Set up a project with a repo directory and active session."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    setup_project(cfg, "myapp", str(repo_dir))
    state.set_session_active("myapp")
    return cfg, "myapp", repo_dir


@pytest.fixture()
def project_with_agent_file(
    cfg: ProjConfig, tmp_path: Path
) -> tuple[ProjConfig, str, Path]:
    """Set up a project with a repo that has a .claude/agents/MyAgent.md file."""
    repo_dir = tmp_path / "repo"
    agents_dir = repo_dir / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "MyAgent.md").write_text("# MyAgent\n")
    setup_project(cfg, "myapp", str(repo_dir))
    state.set_session_active("myapp")
    return cfg, "myapp", repo_dir


@pytest.mark.asyncio
class TestProjSetAgent:
    async def test_happy_path_sets_override(
        self, agents_app: Any, project_with_agent_file: tuple[ProjConfig, str, Path]
    ) -> None:
        cfg, name, repo_dir = project_with_agent_file
        result = await call_tool(agents_app, "proj_set_agent", step="define", agent_name="MyAgent")
        assert "MyAgent" in result
        assert "define" in result

        data = storage.load_agents(cfg, name)
        agents_section = data.get("agents", {})
        assert isinstance(agents_section, dict)
        assert agents_section["define"] == "MyAgent"

    async def test_invalid_step_returns_error(
        self, agents_app: Any, project_with_agent_file: tuple[ProjConfig, str, Path]
    ) -> None:
        result = await call_tool(agents_app, "proj_set_agent", step="invalid_step", agent_name="MyAgent")
        assert "Invalid step" in result
        assert "invalid_step" in result

    async def test_agent_file_not_found_returns_error(
        self, agents_app: Any, project_with_repo: tuple[ProjConfig, str, Path]
    ) -> None:
        """Agent file doesn't exist in repo → returns error."""
        cfg, name, repo_dir = project_with_repo
        # No .claude/agents/NonExistent.md exists
        result = await call_tool(agents_app, "proj_set_agent", step="define", agent_name="NonExistent")
        assert "not found" in result.lower() or "NonExistent" in result

    async def test_agents_yaml_auto_created(
        self, agents_app: Any, project_with_agent_file: tuple[ProjConfig, str, Path]
    ) -> None:
        """When agents.yaml doesn't exist yet, it is created automatically."""
        cfg, name, repo_dir = project_with_agent_file
        agents_yaml = storage.agents_path(cfg, name)
        assert not agents_yaml.exists(), "Pre-condition: agents.yaml must not exist"

        result = await call_tool(agents_app, "proj_set_agent", step="research", agent_name="MyAgent")
        assert agents_yaml.exists()
        data = storage.load_agents(cfg, name)
        agents_section = data.get("agents", {})
        assert isinstance(agents_section, dict)
        assert agents_section["research"] == "MyAgent"


@pytest.mark.asyncio
class TestProjGetAgents:
    async def test_no_overrides_shows_all_defaults(
        self, agents_app: Any, project_with_repo: tuple[ProjConfig, str, Path]
    ) -> None:
        """No agents.yaml → all steps show their defaults."""
        result = await call_tool(agents_app, "proj_get_agents")
        assert "myapp" in result
        for step, default in STEP_DEFAULTS.items():
            assert default in result

    async def test_mixed_overrides_shows_correct_mix(
        self, agents_app: Any, project_with_agent_file: tuple[ProjConfig, str, Path]
    ) -> None:
        """Some steps overridden, others at default → output shows correct mix."""
        cfg, name, repo_dir = project_with_agent_file

        # Set define to use MyAgent
        storage.save_agents(
            cfg,
            name,
            {
                "version": 1,
                "agents": {
                    "define": "MyAgent",
                    "research": None,
                    "decompose": None,
                    "execute": None,
                },
            },
        )

        result = await call_tool(agents_app, "proj_get_agents")
        # define step should show MyAgent (the override)
        assert "MyAgent" in result
        # other steps should show defaults
        assert STEP_DEFAULTS["research"] in result
        assert STEP_DEFAULTS["execute"] in result

    async def test_missing_agents_yaml_shows_all_defaults(
        self, agents_app: Any, project_with_repo: tuple[ProjConfig, str, Path]
    ) -> None:
        """Missing agents.yaml → shows all defaults (same as no overrides)."""
        cfg, name, repo_dir = project_with_repo
        # No agents.yaml exists
        result = await call_tool(agents_app, "proj_get_agents")
        for step, default in STEP_DEFAULTS.items():
            assert default in result


@pytest.mark.asyncio
class TestProjRemoveAgent:
    async def test_happy_path_reverts_step_to_null(
        self, agents_app: Any, project_with_agent_file: tuple[ProjConfig, str, Path]
    ) -> None:
        """Remove existing override → step reverted to null in agents.yaml."""
        cfg, name, repo_dir = project_with_agent_file

        # First set an override
        storage.save_agents(
            cfg,
            name,
            {
                "version": 1,
                "agents": {
                    "define": "MyAgent",
                    "research": None,
                    "decompose": None,
                    "execute": None,
                },
            },
        )

        result = await call_tool(agents_app, "proj_remove_agent", step="define")
        assert "define" in result

        data = storage.load_agents(cfg, name)
        agents_section = data.get("agents", {})
        assert isinstance(agents_section, dict)
        assert agents_section.get("define") is None

    async def test_step_already_null_succeeds_silently(
        self, agents_app: Any, project_with_repo: tuple[ProjConfig, str, Path]
    ) -> None:
        """Step already null (agents.yaml missing) → succeeds without error."""
        cfg, name, repo_dir = project_with_repo
        # No agents.yaml — step is already at default
        result = await call_tool(agents_app, "proj_remove_agent", step="execute")
        # Should not return an error — either a success/already-default message
        assert "Invalid" not in result
        assert "error" not in result.lower()

    async def test_invalid_step_returns_error(
        self, agents_app: Any, project_with_repo: tuple[ProjConfig, str, Path]
    ) -> None:
        result = await call_tool(agents_app, "proj_remove_agent", step="bogus_step")
        assert "Invalid step" in result
        assert "bogus_step" in result


@pytest.mark.asyncio
class TestProjResolveAgent:
    async def test_returns_default_agent_and_null_warning_when_no_override(
        self, agents_app: Any, project_with_repo: tuple[ProjConfig, str, Path]
    ) -> None:
        """No override → agent=default, warning=null."""
        result = await call_tool(agents_app, "proj_resolve_agent", step="define")
        data = json.loads(result)
        assert data["agent"] == STEP_DEFAULTS["define"]
        assert data["warning"] is None

    async def test_returns_override_agent_and_null_warning_when_file_exists(
        self, agents_app: Any, project_with_agent_file: tuple[ProjConfig, str, Path]
    ) -> None:
        """Override set + file exists → agent=override, warning=null."""
        cfg, name, repo_dir = project_with_agent_file

        storage.save_agents(cfg, name, {"version": 1, "agents": {"define": "MyAgent"}})

        result = await call_tool(agents_app, "proj_resolve_agent", step="define")
        data = json.loads(result)
        assert data["agent"] == "MyAgent"
        assert data["warning"] is None

    async def test_returns_default_and_warning_when_override_file_missing(
        self, agents_app: Any, project_with_repo: tuple[ProjConfig, str, Path]
    ) -> None:
        """Override set + file not found in repo → agent=default, warning=string."""
        cfg, name, repo_dir = project_with_repo

        storage.save_agents(cfg, name, {"version": 1, "agents": {"research": "GhostAgent"}})

        result = await call_tool(agents_app, "proj_resolve_agent", step="research")
        data = json.loads(result)
        assert data["agent"] == STEP_DEFAULTS["research"]
        assert data["warning"] is not None
        assert isinstance(data["warning"], str)
        assert "GhostAgent" in data["warning"]
