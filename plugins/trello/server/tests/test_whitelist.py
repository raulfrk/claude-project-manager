"""Tests for board whitelist enforcement."""

from __future__ import annotations

import pytest

from server.lib.client import TrelloClient
from server.lib.config import TrelloConfig


class TestCheckBoardAccessEmptyWhitelist:
    def test_empty_whitelist_raises(self) -> None:
        config = TrelloConfig(api_key="k", token="t", allowed_board_ids=[])
        client = TrelloClient.__new__(TrelloClient)
        client._config = config

        with pytest.raises(RuntimeError, match="No boards in whitelist"):
            client.check_board_access("b1")


class TestCheckBoardAccessAllowed:
    def test_listed_board_passes(self) -> None:
        config = TrelloConfig(api_key="k", token="t", allowed_board_ids=["b1", "b2"])
        client = TrelloClient.__new__(TrelloClient)
        client._config = config

        # Should not raise
        client.check_board_access("b1")
        client.check_board_access("b2")


class TestCheckBoardAccessDenied:
    def test_unlisted_board_raises(self) -> None:
        config = TrelloConfig(api_key="k", token="t", allowed_board_ids=["b1"])
        client = TrelloClient.__new__(TrelloClient)
        client._config = config

        with pytest.raises(RuntimeError, match="not in whitelist"):
            client.check_board_access("b999")
