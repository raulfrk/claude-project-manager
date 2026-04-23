"""Tests for server.lib.state."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import state
from server.lib.state import (
    clear_session_active,
    get_session_active,
    resolve_project,
    set_session_active,
)


class TestSessionState:
    def setup_method(self):
        clear_session_active()

    def test_initial_state_is_none(self):
        assert get_session_active() is None

    def test_set_and_get(self):
        set_session_active("myproject")
        assert get_session_active() == "myproject"

    def test_clear(self):
        set_session_active("myproject")
        clear_session_active()
        assert get_session_active() is None

    def test_overwrite(self):
        set_session_active("first")
        set_session_active("second")
        assert get_session_active() == "second"


class TestResolveProject:
    def setup_method(self):
        clear_session_active()

    def test_explicit_name_wins(self):
        set_session_active("session-proj")
        assert resolve_project("explicit") == "explicit"

    def test_falls_back_to_session(self):
        set_session_active("session-proj")
        assert resolve_project(None) == "session-proj"

    def test_returns_none_when_nothing_set(self):
        assert resolve_project(None) is None

    def test_empty_string_falls_back(self):
        set_session_active("session-proj")
        assert resolve_project("") == "session-proj"


@pytest.fixture
def session_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect _SESSION_FILE to a temp path + clear in-memory state."""
    p = tmp_path / "proj-session.yaml"
    monkeypatch.setattr(state, "_SESSION_FILE", p)
    monkeypatch.setattr(state, "_session_active_project", None)
    return p


class TestSessionActivePersistence:
    def test_set_writes_file(self, session_file: Path) -> None:
        set_session_active("my-proj")
        assert session_file.exists()
        content = session_file.read_text()
        assert "my-proj" in content

    def test_get_returns_in_memory_first(self, session_file: Path) -> None:
        set_session_active("in-mem")
        session_file.write_text("active: file-value\n")
        assert get_session_active() == "in-mem"

    def test_get_falls_back_to_file_when_memory_none(
        self, session_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_file.write_text("active: from-file\n")
        monkeypatch.setattr(state, "_session_active_project", None)
        assert get_session_active() == "from-file"

    def test_get_returns_none_when_both_empty(self, session_file: Path) -> None:
        assert get_session_active() is None

    def test_clear_removes_both(self, session_file: Path) -> None:
        set_session_active("x")
        assert session_file.exists()
        clear_session_active()
        assert not session_file.exists()
        assert get_session_active() is None

    def test_clear_when_nothing_set_is_idempotent(self, session_file: Path) -> None:
        clear_session_active()
        assert get_session_active() is None

    def test_file_malformed_falls_back_to_none(
        self, session_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_file.write_text("not: : : valid yaml")
        monkeypatch.setattr(state, "_session_active_project", None)
        assert get_session_active() is None

    def test_round_trip_across_module_reimport(
        self, session_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates MCP server restart: set, clear in-memory, get reads file."""
        set_session_active("survived")
        monkeypatch.setattr(state, "_session_active_project", None)
        assert get_session_active() == "survived"
