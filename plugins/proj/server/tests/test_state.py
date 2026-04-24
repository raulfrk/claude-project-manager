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


@pytest.fixture(autouse=True)
def _redirect_session_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect state._SESSION_FILE to a tmp path for every test in this module.

    Prevents any test from touching the user's real ~/.claude/proj-session.yaml —
    including the non-fixture classes below that call clear_session_active in setup.
    """
    p = tmp_path / "proj-session.yaml"
    monkeypatch.setattr(state, "_SESSION_FILE", p)
    monkeypatch.setattr(state, "_session_active_project", None)


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
        # clear_active leaves a v2 file with an empty active_by_claude_pid map;
        # the important invariant is that get_session_active() returns None.
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


class TestMultiSessionIsolation:
    def test_two_sessions_dont_clobber(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Writes from two distinct session_keys coexist in the file."""
        import os

        # Use real PIDs so _gc_dead_pids doesn't prune them (GC skips non-int keys
        # and prunes dead int keys; real pids of this test process are always alive).
        key1 = str(os.getpid())
        key2 = str(os.getppid())

        # Session 1 writes:
        monkeypatch.setattr(state, "_session_key_fn", lambda: key1)
        set_session_active("proj-a")

        # Simulate a DIFFERENT Claude Code session sharing the same file:
        monkeypatch.setattr(state, "_session_key_fn", lambda: key2)
        state._session_active_project = None  # fresh in-memory (different process)
        set_session_active("proj-b")

        # Session 1 view (fresh in-memory, reads disk):
        monkeypatch.setattr(state, "_session_key_fn", lambda: key1)
        state._session_active_project = None
        assert get_session_active() == "proj-a"

        # Session 2 view:
        monkeypatch.setattr(state, "_session_key_fn", lambda: key2)
        state._session_active_project = None
        assert get_session_active() == "proj-b"

    def test_clear_one_session_leaves_other_intact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import os

        key1 = str(os.getpid())
        key2 = str(os.getppid())

        monkeypatch.setattr(state, "_session_key_fn", lambda: key1)
        set_session_active("proj-a")
        monkeypatch.setattr(state, "_session_key_fn", lambda: key2)
        state._session_active_project = None
        set_session_active("proj-b")

        monkeypatch.setattr(state, "_session_key_fn", lambda: key1)
        state._session_active_project = None
        clear_session_active()

        # key2 still resolves:
        monkeypatch.setattr(state, "_session_key_fn", lambda: key2)
        state._session_active_project = None
        assert get_session_active() == "proj-b"

    def test_read_migrates_v1_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A legacy v1 file → read() returns the scalar for the current session."""
        import os

        import yaml as _yaml

        state._SESSION_FILE.write_text(_yaml.safe_dump({"active": "legacy"}))

        monkeypatch.setattr(state, "_session_key_fn", lambda: str(os.getpid()))
        state._session_active_project = None
        assert get_session_active() == "legacy"
