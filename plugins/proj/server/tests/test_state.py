"""Tests for server.lib.state."""

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
