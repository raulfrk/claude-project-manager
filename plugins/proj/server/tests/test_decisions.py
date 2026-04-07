"""Tests for proj_decision_log MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path / "myrepo"))
    state.set_session_active("myapp")
    return cfg, "myapp"


@pytest.fixture()
def decision_app(cfg: ProjConfig) -> Any:
    """Return a FastMCP app with decisions tool registered."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, decisions

    app = FastMCP("test-decisions")
    config.register(app)
    decisions.register(app)
    return app


@pytest.mark.asyncio
class TestDecisionLog:
    async def test_add_creates_entry_with_timestamp(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Use regex search",
            context="Phase 6 knowledge search",
            todo_id="259.1",
            tags="architecture,search",
        )
        assert "Decision logged" in result
        entries = storage.load_decisions(cfg, name)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["decision"] == "Use regex search"
        assert entry["context"] == "Phase 6 knowledge search"
        assert entry["todo_id"] == "259.1"
        assert entry["tags"] == ["architecture", "search"]
        assert "timestamp" in entry
        # Timestamp should be ISO-ish format
        assert "T" in str(entry["timestamp"])

    async def test_search_by_keyword_returns_matches(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Use regex search, no vector DB",
            context="Phase 6",
        )
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Use YAML for storage",
            context="Data layer",
        )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="regex",
        )
        assert "regex" in result.lower()
        assert "YAML" not in result

    async def test_search_matches_context_field(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Some decision",
            context="Phase 6 knowledge search",
        )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="knowledge",
        )
        assert "Some decision" in result

    async def test_list_returns_recent_entries(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        for i in range(5):
            await call_tool(
                decision_app,
                "proj_decision_log",
                action="add",
                decision=f"Decision {i}",
            )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="list",
        )
        # All 5 should appear (default limit 20)
        for i in range(5):
            assert f"Decision {i}" in result

    async def test_list_respects_count(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        for i in range(5):
            await call_tool(
                decision_app,
                "proj_decision_log",
                action="add",
                decision=f"Decision {i}",
            )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="list",
            decision="2",
        )
        # Only the 2 most recent should appear
        assert "Decision 4" in result
        assert "Decision 3" in result
        assert "Decision 0" not in result

    async def test_list_since_days_filters_by_age(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        now = datetime.now(UTC)
        # Add an old entry (10 days ago) directly to storage
        old_entry = {
            "timestamp": (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S"),
            "decision": "Old decision",
            "context": "",
            "todo_id": "",
            "tags": [],
        }
        storage.append_decision(cfg, name, old_entry)
        # Add a recent entry (1 day ago) directly to storage
        recent_entry = {
            "timestamp": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
            "decision": "Recent decision",
            "context": "",
            "todo_id": "",
            "tags": [],
        }
        storage.append_decision(cfg, name, recent_entry)
        # Filter to last 5 days via context param
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="list",
            context="5",
        )
        assert "Recent decision" in result
        assert "Old decision" not in result

    async def test_empty_decisions_returns_empty(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="list",
        )
        assert "No decisions found" in result

    async def test_search_empty_returns_no_matches(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="nonexistent",
        )
        assert "No decisions" in result

    async def test_decisions_yaml_created_on_first_add(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        path = storage.decisions_path(cfg, name)
        assert not path.exists()
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="First decision",
        )
        assert path.exists()

    async def test_add_without_decision_returns_error(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
        )
        assert "required" in result.lower()

    async def test_unknown_action_returns_error(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="delete",
        )
        assert "Unknown action" in result

    async def test_no_active_project_returns_error(
        self, decision_app: Any, cfg: ProjConfig
    ) -> None:
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="list",
        )
        assert "No active project" in result
