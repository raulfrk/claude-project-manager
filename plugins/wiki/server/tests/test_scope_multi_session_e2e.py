"""End-to-end multi-session isolation test.

Simulates two Claude Code sessions writing via proj's state.set_session_active
and verifies each session's wiki_scope_detect reads back its own active project.
This is the canonical regression test for todo 724.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from tests.conftest import call_tool

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@pytest.mark.asyncio
class TestMultiSessionScopeE2E:
    async def test_two_sessions_isolated_via_pid_keys(
        self,
        mcp_app: FastMCP,
        proj_paths: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulate two sessions writing v2 entries; each sees only its own."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))

        # Simulate session 1 writing its active project:
        proj_paths["session_yaml"].write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "active_by_claude_pid": {
                        "sess-1": {"active": "proj-one", "last_seen": "2026-04-24T10:00:00"},
                        "sess-2": {"active": "proj-two", "last_seen": "2026-04-24T10:00:00"},
                    },
                }
            )
        )

        # wiki running as session 1:
        monkeypatch.setattr("server.tools.scope._session_key_fn", lambda: "sess-1")
        result1 = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result1["scope"] == "project:proj-one"

        # wiki running as session 2 (same file, different session key):
        monkeypatch.setattr("server.tools.scope._session_key_fn", lambda: "sess-2")
        result2 = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result2["scope"] == "project:proj-two"
