"""Tests for server.tools.invocations — MCP invocation history tool."""

from __future__ import annotations

import json
from unittest.mock import patch

from server.tools.invocations import hooks_invocations


def _make_entries(n, type_field="invocation"):
    return [
        {
            "hook_id": f"h{i}",
            "trigger_tool": f"t{i}",
            "target_tool": f"tgt{i}",
            "timestamp": f"2026-01-{i + 1:02d}T00:00:00",
        }
        for i in range(n)
    ]


class TestHooksInvocations:
    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(3))
    def test_returns_all_invocations(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations())
        assert result["total"] == 3

    @patch(
        "server.tools.invocations.storage.load_failures", return_value=_make_entries(2, "failure")
    )
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(2))
    def test_combines_invocations_and_failures(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(type="all"))
        assert result["total"] == 4

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(3))
    def test_filter_by_hook_id(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(hook_id="h1"))
        assert all(e["hook_id"] == "h1" for e in result["entries"])

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(3))
    def test_filter_by_trigger_tool(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(trigger_tool="t0"))
        assert all(e["trigger_tool"] == "t0" for e in result["entries"])

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(300))
    def test_limit_clamped_to_200(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(limit=500))
        assert result["limit"] == 200
        assert len(result["entries"]) <= 200

    @patch("server.tools.invocations.storage.load_failures", return_value=_make_entries(2))
    @patch("server.tools.invocations.storage.load_invocations", return_value=[])
    def test_type_failure_only(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(type="failure"))
        assert result["total"] == 2

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(2))
    def test_type_invocation_only(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(type="invocation"))
        assert result["total"] == 2

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(5))
    def test_sorted_newest_first(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations())
        timestamps = [e["timestamp"] for e in result["entries"]]
        assert timestamps == sorted(timestamps, reverse=True)
