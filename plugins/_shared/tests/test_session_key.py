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

    def test_v1_file_migrates_in_memory_returns_active(self, tmp_path: Path) -> None:
        """v1 flat scalar file → read returns active; file NOT rewritten."""
        f = tmp_path / "proj-session.yaml"
        _write_yaml(f, {"active": "legacy-proj"})
        assert sk.read_active(f, session_key="100") == "legacy-proj"
        # read_active is read-only — file stays v1 on disk:
        data = yaml.safe_load(f.read_text())
        assert "schema_version" not in data
        assert data["active"] == "legacy-proj"

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


class TestWriteActive:
    def test_write_creates_file_with_v2_schema(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "my-proj", session_key="100")

        assert f.exists()
        data = yaml.safe_load(f.read_text())
        assert data["schema_version"] == 2
        assert data["active_by_claude_pid"]["100"]["active"] == "my-proj"
        assert "last_seen" in data["active_by_claude_pid"]["100"]

    def test_write_preserves_other_sessions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "200": {"active": "other", "last_seen": "2026-04-24T10:00:00"},
                },
            },
        )
        # both pids alive so GC does not prune pid 200:
        monkeypatch.setattr(sk.psutil, "pid_exists", lambda pid: pid in (100, 200))
        sk.write_active(f, "mine", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert data["active_by_claude_pid"]["200"]["active"] == "other"
        assert data["active_by_claude_pid"]["100"]["active"] == "mine"

    def test_write_overwrites_own_session(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "first", session_key="100")
        sk.write_active(f, "second", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert data["active_by_claude_pid"]["100"]["active"] == "second"

    def test_gc_prunes_dead_pids_on_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "100": {"active": "live-proj", "last_seen": "2026-04-24T10:00:00"},
                    "999": {"active": "dead-proj", "last_seen": "2026-04-20T10:00:00"},
                },
            },
        )
        # pid 100 alive, 999 dead:
        monkeypatch.setattr(sk.psutil, "pid_exists", lambda pid: pid == 100)

        sk.write_active(f, "updated", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert "100" in data["active_by_claude_pid"]
        assert "999" not in data["active_by_claude_pid"]

    def test_write_migrates_v1_file(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(f, {"active": "legacy-proj"})  # v1 shape
        sk.write_active(f, "new-proj", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert data["schema_version"] == 2
        assert "active" not in data  # v1 key removed
        assert data["active_by_claude_pid"]["100"]["active"] == "new-proj"

    def test_write_is_atomic(self, tmp_path: Path) -> None:
        """Tmpfile should be renamed, not left behind."""
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "proj", session_key="100")

        # No .tmp* siblings left behind:
        siblings = list(tmp_path.iterdir())
        assert all(not s.name.startswith(".proj-session.yaml.") for s in siblings)


class TestClearActive:
    def test_clear_removes_own_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "proj-session.yaml"
        # Both pids kept alive so GC does not prune them — ensures pop() is the
        # actual mechanism removing "100", not GC silently discarding it first.
        monkeypatch.setattr(sk.psutil, "pid_exists", lambda pid: True)
        sk.write_active(f, "mine", session_key="100")
        sk.write_active(f, "theirs", session_key="200")

        sk.clear_active(f, session_key="100")

        data = yaml.safe_load(f.read_text())
        assert "100" not in data["active_by_claude_pid"]
        assert data["active_by_claude_pid"]["200"]["active"] == "theirs"

    def test_clear_on_missing_file_is_noop(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        # No file yet. Should not raise.
        sk.clear_active(f, session_key="100")
        assert not f.exists()

    def test_clear_last_session_leaves_empty_structure(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "only", session_key="100")

        sk.clear_active(f, session_key="100")

        # File still exists w/ empty mapping — not deleted (preserves schema).
        data = yaml.safe_load(f.read_text())
        assert data["schema_version"] == 2
        assert data["active_by_claude_pid"] == {}
