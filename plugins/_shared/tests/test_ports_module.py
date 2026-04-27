"""Tests for plugins/_shared/hook_transport/ports.py."""

from __future__ import annotations

import pytest

from hook_transport.ports import port_for


def test_port_for_known_plugin():
    """Known plugin returns int port."""
    assert port_for("proj") == 19102
    assert port_for("router") == 19100
    assert port_for("wiki") == 19109


def test_port_for_unknown_raises_keyerror():
    """Unknown plugin raises KeyError w/ descriptive message."""
    with pytest.raises(KeyError, match="unknown plugin"):
        port_for("nonexistent")


def test_port_for_returns_int():
    """Return value is always int (not str)."""
    result = port_for("proj")
    assert isinstance(result, int)


def test_port_for_all_canonical_plugins():
    """All 9 canonical plugin names resolve."""
    for name in [
        "router",
        "proj",
        "worktree",
        "trello",
        "jira",
        "todoist",
        "zoxide",
        "confluence",
        "wiki",
    ]:
        assert isinstance(port_for(name), int)
