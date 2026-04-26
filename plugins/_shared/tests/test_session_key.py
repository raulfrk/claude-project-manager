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

    def test_falls_back_to_ppid_when_execpath_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bug 779: when EXECPATH is unset (plugin MCP server context), the
        resolver returns os.getppid(), not os.getpid(). MCP servers' ppid IS
        the long-lived claude-bin that owns the session, so ppid is the same
        pid the EXECPATH walk would resolve for a hook subprocess. Both code
        paths converge on a single proj-session.yaml slot.
        """
        from session_key.session_key import get_claude_session_key

        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        assert get_claude_session_key() == str(os.getppid())

    def test_mcp_server_resolution_uses_ppid_when_execpath_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bug 779 regression: simulate plugin MCP server context.

        Claude Code launches plugins via ``.mcp.json`` -> ``bash start.sh`` ->
        ``exec python -m server.main``. The exec preserves the bash pid+ppid,
        so the python process's ppid IS the spawning claude-bin. CLAUDE_CODE_
        EXECPATH is NOT propagated to plugin MCP subprocesses (only to hook
        subprocesses). Verify resolver returns ppid in that scenario, matching
        what a hook subprocess would resolve via the EXECPATH walk.
        """
        from session_key.session_key import get_claude_session_key

        # MCP server context: no EXECPATH, ppid is the (mocked) parent claude.
        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        monkeypatch.setattr(os, "getppid", lambda: 186785)

        assert get_claude_session_key() == "186785"

    def test_direct_parent_match_returns_ppid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the only matching ancestor IS the immediate parent, resolver
        returns ppid. (No fast path post-775; this exercises the walk path
        with a single matching ancestor.)
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 1234)

        claude_parent = _FakeProc(pid=1234, exe="/usr/bin/claude")

        # Process() (no arg) returns self whose parents() yields [claude_parent].
        def fake_process(pid=None):
            if pid == 1234:
                return claude_parent
            return _FakeProc(pid=os.getpid(), parents_=[claude_parent])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
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

    def test_no_ancestor_matches_falls_back_to_ppid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Walk-failed fallback returns os.getppid() (not os.getpid()).

        Bug 779 follow-up: Claude Code's hook execution path on ``--resume``
        can sever the parent chain (subreaper / setsid detach), so the
        EXECPATH walk finds no claude ancestor. Falling back to ppid converges
        with what the MCP-server-fallback path produces (same logic as the
        EXECPATH-unset branch); falling back to own pid would diverge from
        what MCP servers see, breaking ``proj-session.yaml`` lookups.
        """
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

        assert sk.get_claude_session_key() == "5000"

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

        claude_parent = _FakeProc(pid=4242, exe="/usr/bin/claude")  # also a symlink

        def fake_process(pid=None):
            if pid == 4242:
                return claude_parent
            return _FakeProc(pid=os.getpid(), parents_=[claude_parent])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)

        def fake_realpath(p: str) -> str:
            if p == "/usr/bin/claude":
                return "/opt/claude/bin/claude"
            return p

        monkeypatch.setattr(sk.os.path, "realpath", fake_realpath)

        assert sk.get_claude_session_key() == "4242"

    def test_outermost_match_when_multiple_claude_ancestors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bug 775 regression: when both INNER and OUTER claude-bin processes
        appear in the ancestor chain (because Claude self-forks for hook
        execution), the resolver must return OUTER (outermost match), not
        INNER (first match).

        Process tree under SessionStart hook (CLI's view, walking up):
            shell → INNER claude-bin → OUTER claude-bin → terminal/launcher
        Both INNER and OUTER exes match EXECPATH; the launcher does not.
        Expected resolver result: OUTER.pid.
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 5000)  # immediate parent: shell

        shell_proc = _FakeProc(pid=5000, exe="/bin/bash")
        inner_claude = _FakeProc(pid=100, exe="/usr/bin/claude")
        outer_claude = _FakeProc(pid=200, exe="/usr/bin/claude")
        launcher = _FakeProc(pid=1, exe="/sbin/init")

        # parents() yields ancestors immediate-first (psutil contract).
        def fake_process(pid=None):
            if pid == 5000:
                return shell_proc
            return _FakeProc(
                pid=os.getpid(),
                parents_=[shell_proc, inner_claude, outer_claude, launcher],
            )

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        # Outermost match wins → OUTER.pid (200), NOT INNER.pid (100).
        assert sk.get_claude_session_key() == "200"

    def test_ppid_match_does_not_short_circuit_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confirms fast path is gone (post-775).

        os.getppid() returns a pid whose exe matches EXECPATH AND there's a
        deeper ancestor that ALSO matches. The deeper (outermost) ancestor
        must win — proving resolver no longer short-circuits on ppid match.
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 100)  # immediate parent matches

        inner_claude = _FakeProc(pid=100, exe="/usr/bin/claude")
        outer_claude = _FakeProc(pid=200, exe="/usr/bin/claude")
        launcher = _FakeProc(pid=1, exe="/sbin/init")

        def fake_process(pid=None):
            if pid == 100:
                return inner_claude
            return _FakeProc(
                pid=os.getpid(),
                parents_=[inner_claude, outer_claude, launcher],
            )

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        # Even with ppid matching, outermost wins.
        assert sk.get_claude_session_key() == "200"

    def test_outermost_match_with_dead_pid_in_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One ancestor in the fork chain is dead (raises NoSuchProcess on
        .exe()). Walk must continue and return the outermost LIVE match.
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 7000)

        shell_proc = _FakeProc(pid=7000, exe="/bin/bash")
        inner_claude = _FakeProc(pid=100, exe="/usr/bin/claude")
        dead_proc = _FakeProc(pid=150, exe_raises=True)
        outer_claude = _FakeProc(pid=200, exe="/usr/bin/claude")
        launcher = _FakeProc(pid=1, exe="/sbin/init")

        def fake_process(pid=None):
            if pid == 7000:
                return shell_proc
            return _FakeProc(
                pid=os.getpid(),
                parents_=[shell_proc, inner_claude, dead_proc, outer_claude, launcher],
            )

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        # Dead ancestor between INNER and OUTER does NOT short-circuit walk.
        assert sk.get_claude_session_key() == "200"


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

    def test_write_active_cleans_legacy_marker_dir_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First write_active call removes ~/.claude/proj-session-markers/.

        Subsequent calls in the same process skip the cleanup (guarded by a
        module-level flag).
        """
        # Reset the module-level guard so this test isn't order-dependent.
        monkeypatch.setattr(sk, "_legacy_cleanup_done", False)

        # Synthetic legacy marker dir under tmp_path.
        legacy = tmp_path / "proj-session-markers"
        legacy.mkdir()
        (legacy / "1234.yaml").write_text("ns_inode: 0\nstarted: '2026-01-01T00:00:00+00:00'\n")
        monkeypatch.setattr(sk, "_LEGACY_MARKER_DIR", legacy)

        target = tmp_path / "proj-session.yaml"
        sk.write_active(target, "proj-x", session_key="100")

        # First call: legacy dir gone.
        assert not legacy.exists()

        # Recreate it; a second call should NOT remove it (guard prevents).
        legacy.mkdir()
        (legacy / "5678.yaml").write_text("ns_inode: 0\n")
        sk.write_active(target, "proj-y", session_key="100")
        assert legacy.exists(), "Second write_active should be a no-op for legacy cleanup"


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
