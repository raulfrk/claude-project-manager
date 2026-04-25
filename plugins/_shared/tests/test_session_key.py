"""Unit tests for session_key helper."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import yaml

from session_key import session_key as sk

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _FakeProc:
    """Minimal psutil.Process stub for resolver tests."""

    def __init__(
        self,
        pid: int,
        exe: str = "",
        exe_raises: bool = False,
        parents_: list[_FakeProc] | None = None,
    ) -> None:
        self.pid = pid
        self._exe = exe
        self._exe_raises = exe_raises
        self._parents = parents_ or []

    def exe(self) -> str:
        if self._exe_raises:
            import psutil

            raise psutil.NoSuchProcess(self.pid)
        return self._exe

    def parents(self) -> list[_FakeProc]:
        return self._parents

    # Legacy fields kept for any pre-existing tests that still reference them.
    def cmdline(self) -> list[str]:
        return []


class TestGetClaudeSessionKey:
    """EXECPATH-based ancestor-walk resolver tests.

    The resolver matches ancestor processes by canonical exe path
    (CLAUDE_CODE_EXECPATH realpath) — no cmdline regex, no marker files.
    """

    def test_falls_back_to_own_pid_when_execpath_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from session_key.session_key import get_claude_session_key

        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        assert get_claude_session_key() == str(os.getpid())

    def test_direct_parent_match_returns_ppid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fast path: os.getppid()'s exe matches EXECPATH → return ppid."""
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 1234)

        fake_parent = _FakeProc(pid=1234, exe="/usr/bin/claude")
        # psutil.Process(1234).exe() must return the EXECPATH for the fast path.
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_parent)
        # realpath is identity for these absolute paths
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == "1234"

    def test_mid_chain_ancestor_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Direct parent doesn't match; an ancestor higher in the chain does."""
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        # Direct parent is uv (no match); two hops up is claude.
        monkeypatch.setattr(sk.os, "getppid", lambda: 9001)
        uv_proc = _FakeProc(pid=9001, exe="/usr/bin/uv")
        bash_proc = _FakeProc(pid=9000, exe="/bin/bash")
        claude_proc = _FakeProc(pid=8999, exe="/usr/bin/claude")

        # Process(ppid=9001) returns uv_proc; Process() (no arg) returns self
        # whose .parents() yields [uv, bash, claude].
        def fake_process(pid=None):
            if pid == 9001:
                return uv_proc
            return _FakeProc(pid=os.getpid(), parents_=[uv_proc, bash_proc, claude_proc])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == "8999"

    def test_no_ancestor_matches_falls_back_to_own_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 5000)
        bash_proc = _FakeProc(pid=5000, exe="/bin/bash")
        sh_proc = _FakeProc(pid=4999, exe="/bin/sh")

        def fake_process(pid=None):
            if pid == 5000:
                return bash_proc
            return _FakeProc(pid=os.getpid(), parents_=[bash_proc, sh_proc])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == str(os.getpid())

    def test_no_such_process_mid_walk_continues(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One ancestor raises NoSuchProcess; walk continues to find next match."""
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 7000)

        # Direct parent: bash (no match). One ancestor raises; the next matches.
        bash_proc = _FakeProc(pid=7000, exe="/bin/bash")
        dead_proc = _FakeProc(pid=6999, exe_raises=True)
        claude_proc = _FakeProc(pid=6998, exe="/usr/bin/claude")

        def fake_process(pid=None):
            if pid == 7000:
                return bash_proc
            return _FakeProc(pid=os.getpid(), parents_=[bash_proc, dead_proc, claude_proc])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == "6998"

    def test_realpath_normalization(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EXECPATH and ancestor exe both go through realpath() — symlinks resolve."""
        from session_key import session_key as sk

        # EXECPATH is /usr/bin/claude (a symlink); realpath → /opt/claude/bin/claude.
        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 4242)
        parent = _FakeProc(pid=4242, exe="/usr/bin/claude")  # also a symlink

        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: parent)

        def fake_realpath(p: str) -> str:
            if p == "/usr/bin/claude":
                return "/opt/claude/bin/claude"
            return p

        monkeypatch.setattr(sk.os.path, "realpath", fake_realpath)

        assert sk.get_claude_session_key() == "4242"


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
