"""Tests for proj_session_digest MCP tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project


SESSION_A = """\
# Session: 2026-03-20

## Key Decisions
- Decided to use YAML for config
- Switched to FastMCP for tool registration

## Todos Worked On
- 1: Setup config loader

## Insights Discovered
- FastMCP auto-generates JSON schema from type hints
- YAML is easier to hand-edit than JSON

## Open Questions
- Should we support TOML as an alternative?
"""

SESSION_B = """\
# Session: 2026-03-21

## Key Decisions
- Added retry logic for external API calls
- Decided to use YAML for config

## Todos Worked On
- 2: Add retry helper

## Insights Discovered
- Exponential backoff works better than linear for rate limits

## Open Questions
- Should we support TOML as an alternative?
- What is the max retry count before giving up?
"""

SESSION_C = """\
# Session: 2026-03-22

## Key Decisions
- Implemented session digest tool

## Insights Discovered
- Regex section splitting handles edge cases well

## Open Questions
- How should we handle sessions with no sections?
"""


@pytest.fixture()
def project_with_sessions(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    """Set up a project with three session files."""
    setup_project(cfg, "myapp", str(tmp_path / "myrepo"))
    state.set_session_active("myapp")
    sess_dir = storage.sessions_dir(cfg, "myapp")
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "session-2026-03-20.md").write_text(SESSION_A)
    (sess_dir / "session-2026-03-21.md").write_text(SESSION_B)
    (sess_dir / "session-2026-03-22.md").write_text(SESSION_C)
    return cfg, "myapp"


@pytest.fixture()
def digest_app(cfg: ProjConfig):  # type: ignore[no-untyped-def]
    """Return a FastMCP app with digest tool registered."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config as config_mod, digest, projects

    app = FastMCP("test-digest")
    config_mod.register(app)
    projects.register(app)
    digest.register(app)
    return app


@pytest.mark.asyncio
class TestProjSessionDigest:
    async def test_aggregates_all_sessions(
        self, digest_app, project_with_sessions: tuple[ProjConfig, str]  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest", last_n=3, focus="all")
        data = json.loads(result)
        assert data["focus"] == "all"
        assert data["sessions_read"] == 3
        # All three categories present
        assert "decisions" in data
        assert "questions" in data
        assert "insights" in data
        # Decisions from all sessions
        assert "Decided to use YAML for config" in data["decisions"]
        assert "Implemented session digest tool" in data["decisions"]

    async def test_focus_decisions(
        self, digest_app, project_with_sessions: tuple[ProjConfig, str]  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest", last_n=3, focus="decisions")
        data = json.loads(result)
        assert data["focus"] == "decisions"
        assert "decisions" in data
        # Only decisions key, no questions or insights
        assert "questions" not in data
        assert "insights" not in data
        assert "Switched to FastMCP for tool registration" in data["decisions"]

    async def test_focus_questions(
        self, digest_app, project_with_sessions: tuple[ProjConfig, str]  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest", last_n=3, focus="questions")
        data = json.loads(result)
        assert data["focus"] == "questions"
        assert "questions" in data
        assert "Should we support TOML as an alternative?" in data["questions"]

    async def test_focus_insights(
        self, digest_app, project_with_sessions: tuple[ProjConfig, str]  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest", last_n=3, focus="insights")
        data = json.loads(result)
        assert data["focus"] == "insights"
        assert "insights" in data
        assert "Regex section splitting handles edge cases well" in data["insights"]

    async def test_deduplication(
        self, digest_app, project_with_sessions: tuple[ProjConfig, str]  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest", last_n=3, focus="all")
        data = json.loads(result)
        # "Decided to use YAML for config" appears in both session A and B
        assert data["decisions"].count("Decided to use YAML for config") == 1
        # "Should we support TOML as an alternative?" appears in both A and B
        assert data["questions"].count("Should we support TOML as an alternative?") == 1

    async def test_last_n_limits_sessions(
        self, digest_app, project_with_sessions: tuple[ProjConfig, str]  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest", last_n=1, focus="all")
        data = json.loads(result)
        assert data["sessions_read"] == 1
        # Only session C (the last one) should be included
        assert "Implemented session digest tool" in data["decisions"]
        # Session A/B decisions should not be present
        assert "Decided to use YAML for config" not in data["decisions"]
        assert "Added retry logic for external API calls" not in data["decisions"]

    async def test_empty_sessions_dir(
        self, digest_app, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        setup_project(cfg, "empty", str(tmp_path / "emptyrepo"))
        state.set_session_active("empty")
        # sessions dir does not exist
        result = await call_tool(digest_app, "proj_session_digest")
        data = json.loads(result)
        assert data["sessions_read"] == 0
        assert data["decisions"] == []
        assert data["questions"] == []
        assert data["insights"] == []

    async def test_empty_sessions_dir_exists_but_no_files(
        self, digest_app, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        setup_project(cfg, "nofiles", str(tmp_path / "norepo"))
        state.set_session_active("nofiles")
        sess_dir = storage.sessions_dir(cfg, "nofiles")
        sess_dir.mkdir(parents=True, exist_ok=True)
        result = await call_tool(digest_app, "proj_session_digest")
        data = json.loads(result)
        assert data["sessions_read"] == 0
        assert data["decisions"] == []

    async def test_no_active_project(
        self, digest_app, cfg: ProjConfig  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest")
        assert "No active project" in result

    async def test_invalid_focus(
        self, digest_app, project_with_sessions: tuple[ProjConfig, str]  # type: ignore[type-arg]
    ) -> None:
        result = await call_tool(digest_app, "proj_session_digest", focus="invalid")
        assert "Invalid focus" in result

    async def test_project_name_override(
        self, digest_app, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        setup_project(cfg, "other", str(tmp_path / "otherrepo"))
        sess_dir = storage.sessions_dir(cfg, "other")
        sess_dir.mkdir(parents=True, exist_ok=True)
        (sess_dir / "session-2026-03-25.md").write_text(
            "# Session: 2026-03-25\n\n## Key Decisions\n- Override project test\n"
        )
        result = await call_tool(
            digest_app, "proj_session_digest", project_name="other", focus="decisions"
        )
        data = json.loads(result)
        assert "Override project test" in data["decisions"]
