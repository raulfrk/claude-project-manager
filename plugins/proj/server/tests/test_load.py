"""Tests for proj_load_session and session-scoped active project override."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project



@pytest.fixture()
def two_projects(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str, str]:
    """Create two projects: 'alpha' (active) and 'beta'."""
    setup_project(cfg, "alpha", str(tmp_path / "alpha"))
    setup_project(cfg, "beta", str(tmp_path / "beta"))
    # Make alpha the persisted active
    index = storage.load_index(cfg)
    index.active = "alpha"
    storage.save_index(cfg, index)
    return cfg, "alpha", "beta"


class TestSessionState:
    """Unit tests for the state module directly."""

    def test_initial_state_is_none(self) -> None:
        assert state.get_session_active() is None

    def test_set_and_get(self) -> None:
        state.set_session_active("myproject")
        assert state.get_session_active() == "myproject"

    def test_clear(self) -> None:
        state.set_session_active("myproject")
        state.clear_session_active()
        assert state.get_session_active() is None

    def test_overwrite(self) -> None:
        state.set_session_active("first")
        state.set_session_active("second")
        assert state.get_session_active() == "second"


@pytest.mark.asyncio
class TestProjLoadSession:
    """Tests for the proj_load_session MCP tool."""

    async def test_load_exact_name(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        result = await call_tool(mcp_app, "proj_load_session", name="beta")
        assert "beta" in result
        assert "Loaded" in result
        assert state.get_session_active() == "beta"

    async def test_load_sets_session_override(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        cfg = two_projects[0]
        # Persisted active is "alpha"
        assert storage.load_index(cfg).active == "alpha"
        # Load "beta" for this session
        await call_tool(mcp_app, "proj_load_session", name="beta")
        # Session override is now "beta", persisted active unchanged
        assert state.get_session_active() == "beta"
        assert storage.load_index(cfg).active == "alpha"

    async def test_load_unknown_name_returns_error(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        result = await call_tool(mcp_app, "proj_load_session", name="zzznomatch999")
        assert "not found" in result.lower()
        assert state.get_session_active() is None

    async def test_load_fuzzy_match_single(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        # "alph" is close enough to "alpha" (cutoff=0.4)
        result = await call_tool(mcp_app, "proj_load_session", name="alph")
        assert "alpha" in result
        assert state.get_session_active() == "alpha"

    async def test_load_ambiguous_match_returns_choices(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        # Create projects whose names would both match a query
        setup_project(cfg, "api-backend", str(tmp_path / "api-backend"))
        setup_project(cfg, "api-frontend", str(tmp_path / "api-frontend"))
        result = await call_tool(mcp_app, "proj_load_session", name="api")
        # Should return ambiguous message with options, not set anything
        assert "ambiguous" in result.lower() or "did you mean" in result.lower()
        assert state.get_session_active() is None

    async def test_load_not_found_lists_available(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        result = await call_tool(mcp_app, "proj_load_session", name="zzznomatch999")
        assert "alpha" in result or "beta" in result


@pytest.mark.asyncio
class TestProjGetActiveWithSessionOverride:
    """Tests that proj_get_active respects the session override."""

    async def test_session_override_takes_precedence(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        # Persisted active is "alpha"; set session override to "beta"
        state.set_session_active("beta")
        result = await call_tool(mcp_app, "proj_get_active")
        assert "beta" in result
        assert "alpha" not in result

    async def test_no_session_active_returns_error(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        # No session override loaded; proj_get_active should return an error
        result = await call_tool(mcp_app, "proj_get_active")
        assert "No active project" in result

    async def test_invalid_session_override_returns_error(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        # Session override points to a project not in the index
        state.set_session_active("deleted-project")
        result = await call_tool(mcp_app, "proj_get_active")
        # No fallback to global active — returns error
        assert "No active project" in result


@pytest.mark.asyncio
class TestCtxSessionStartWithSessionOverride:
    """Tests that ctx_session_start respects the session override."""

    async def test_session_override_used_in_context(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        # Load beta into session; ctx_session_start should show beta's context
        state.set_session_active("beta")
        result = await call_tool(mcp_app, "ctx_session_start")
        assert "beta" in result
        assert "alpha" not in result

    async def test_no_session_override_no_cwd_returns_empty(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str]
    ) -> None:
        # No session override, no cwd → no project can be determined
        result = await call_tool(mcp_app, "ctx_session_start")
        assert result == ""

    async def test_no_override_cwd_autodetects_session(
        self, mcp_app: Any, two_projects: tuple[ProjConfig, str, str], tmp_path: Path
    ) -> None:
        # No session override, but cwd matches alpha → auto-detect sets session active
        result = await call_tool(mcp_app, "ctx_session_start", cwd=str(tmp_path / "alpha"))
        assert "alpha" in result
        assert state.get_session_active() == "alpha"
