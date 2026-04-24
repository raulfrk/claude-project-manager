"""Unit tests for session_key helper."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import yaml

from session_key import session_key as sk

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _FakeProc:
    def __init__(self, pid: int, cmdline: list[str]) -> None:
        self.pid = pid
        self._cmdline = cmdline

    def cmdline(self) -> list[str]:
        return self._cmdline


class TestGetClaudeSessionKey:
    def test_returns_ancestor_pid_when_claude_in_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        own_pid = 1001
        monkeypatch.setattr(sk.os, "getpid", lambda: own_pid)

        chain = [
            _FakeProc(2002, ["uv", "run", "proj-server"]),
            _FakeProc(3003, ["/usr/local/bin/claude"]),
            _FakeProc(4004, ["/bin/zsh"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == "3003"

    def test_falls_back_to_own_pid_if_no_claude_ancestor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        own_pid = 7777
        monkeypatch.setattr(sk.os, "getpid", lambda: own_pid)

        chain = [
            _FakeProc(2002, ["uv"]),
            _FakeProc(3003, ["/bin/zsh"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == str(own_pid)

    def test_matcher_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER", r"^node.+myclaude$")
        monkeypatch.setattr(sk.os, "getpid", lambda: 1)

        chain = [
            _FakeProc(5005, ["node", "/opt/myclaude"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == "5005"

    def test_default_matcher_ignores_wrapper_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`uv run claude-server` must NOT match — only the actual `claude` binary."""
        monkeypatch.delenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER", raising=False)
        monkeypatch.setattr(sk.os, "getpid", lambda: 1)

        chain = [
            _FakeProc(2002, ["uv", "run", "proj-server"]),
            _FakeProc(4004, ["/bin/zsh"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == "1"  # fallback to own pid


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))


class TestReadActive:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        assert sk.read_active(f, session_key="100") is None

    def test_v2_hit_returns_active(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "100": {"active": "proj-a", "last_seen": "2026-04-24T10:00:00"},
                    "200": {"active": "proj-b", "last_seen": "2026-04-24T11:00:00"},
                },
            },
        )
        assert sk.read_active(f, session_key="100") == "proj-a"
        assert sk.read_active(f, session_key="200") == "proj-b"

    def test_v2_miss_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "100": {"active": "proj-a", "last_seen": "2026-04-24T10:00:00"},
                },
            },
        )
        assert sk.read_active(f, session_key="999") is None

    def test_malformed_yaml_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        f.write_text("this: is: not: : valid")
        assert sk.read_active(f, session_key="100") is None

    def test_v2_entry_without_active_field_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {"100": {"last_seen": "2026-04-24T10:00:00"}},
            },
        )
        assert sk.read_active(f, session_key="100") is None

    def test_uses_detected_key_when_session_key_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sk, "get_claude_session_key", lambda: "777")
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {"777": {"active": "auto", "last_seen": "x"}},
            },
        )
        assert sk.read_active(f) == "auto"
