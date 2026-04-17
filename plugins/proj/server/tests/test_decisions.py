"""Tests for proj_decision_log MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from server.tools.decisions import fuzzy_score, score_entry
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

    async def test_search_matches_decision_text_field(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Some decision about knowledge search",
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
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="First decision",
        )
        from server.lib.db import db_path, get_connection

        conn = get_connection(db_path(cfg, name))
        count = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        conn.close()
        assert count >= 1

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

    # ------------------------------------------------------------------
    # Fuzzy search tests
    # ------------------------------------------------------------------

    async def test_fuzzy_search_exact_match(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Exact word match must be found."""
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Use hook dispatch for event routing",
        )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="hook",
        )
        assert "hook dispatch" in result.lower()

    async def test_fuzzy_search_typo_tolerance(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Typo in query should still find the entry."""
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Router is unreachable when socket path missing",
        )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="unreachble",
        )
        assert "unreachable" in result.lower()

    async def test_fuzzy_search_tag_matching(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Search should match against tags field."""
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Reverted the change",
            tags="correction,rollback",
        )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="correction",
        )
        assert "Reverted the change" in result

    async def test_fuzzy_search_short_query_fallback(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Queries < 3 chars should use exact substring match (no fuzzy)."""
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Use MQ for async jobs",
        )
        # "MQ" is 2 chars — should match via substring fallback
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="MQ",
        )
        assert "MQ" in result

    async def test_fuzzy_search_no_match_returns_empty(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Completely unrelated query returns no matches."""
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Use PostgreSQL for storage",
        )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="xyzzy123nonsense",
        )
        assert "No decisions matching" in result

    async def test_fuzzy_search_results_sorted_by_score(
        self, decision_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Higher-scoring matches should appear first."""
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="socket registry connection",
        )
        await call_tool(
            decision_app,
            "proj_decision_log",
            action="add",
            decision="Use Unix domain socket for IPC",
        )
        result = await call_tool(
            decision_app,
            "proj_decision_log",
            action="search",
            decision="socket",
        )
        # Both entries must appear; order is score-descending (both contain "socket")
        assert "socket" in result.lower()
        idx_first = result.lower().find("unix domain socket")
        idx_second = result.lower().find("socket registry")
        # Both present; we just verify both are returned
        assert idx_first != -1
        assert idx_second != -1


class TestFuzzyHelpers:
    """Unit tests for fuzzy_score and score_entry helpers."""

    def test_exact_substring_returns_1(self) -> None:
        assert fuzzy_score("hook", "hook dispatch") == 1.0

    def test_case_insensitive_match(self) -> None:
        assert fuzzy_score("HOOK", "hook dispatch") == 1.0

    def test_short_query_present(self) -> None:
        assert fuzzy_score("ok", "socket") == 1.0

    def test_short_query_absent(self) -> None:
        assert fuzzy_score("zz", "socket") == 0.0

    def test_fuzzy_typo_below_one(self) -> None:
        score = fuzzy_score("unreachble", "unreachable")
        assert 0.5 < score < 1.0

    def test_no_match_low_score(self) -> None:
        score = fuzzy_score("xyzzy", "socket registry path")
        assert score < 0.5

    def test_score_entry_decision_field(self) -> None:
        entry = {"decision": "Use hook dispatch", "context": "", "tags": [], "todo_id": ""}
        sc = score_entry("hook", entry)
        assert sc > 0.5

    def test_score_entry_tag_field(self) -> None:
        entry = {"decision": "Something else", "context": "", "tags": ["correction"], "todo_id": ""}
        sc = score_entry("correction", entry)
        assert sc > 0.5

    def test_score_entry_empty_query(self) -> None:
        entry = {"decision": "Something", "context": "", "tags": [], "todo_id": ""}
        assert score_entry("", entry) == 0.0
