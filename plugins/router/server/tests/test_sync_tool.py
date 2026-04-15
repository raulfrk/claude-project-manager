"""Tests for server.tools.sync — MCP hook sync tool."""

from __future__ import annotations

import json
from unittest.mock import patch

from server.tools.sync import hooks_sync


class TestHooksSync:
    def test_returns_json_with_result(self):
        with patch("server.tools.sync.run_discovery", return_value="Discovered 3 hooks"):
            result = json.loads(hooks_sync())
        assert result["result"] == "Discovered 3 hooks"

    def test_calls_run_discovery(self):
        with patch("server.tools.sync.run_discovery", return_value="ok") as mock:
            hooks_sync()
        mock.assert_called_once()
