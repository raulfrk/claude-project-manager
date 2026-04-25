# installer/tests/test_kill_stale.py
"""Tests for installer.flow.kill_stale — stale Claude Code session detection + kill."""

from __future__ import annotations

import os
import signal
from unittest.mock import MagicMock, patch, call

import pytest
from rich.console import Console


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc_info(pid: int, cmdline: list[str]) -> MagicMock:
    """Build a fake psutil.Process-like object for process_iter mocks."""
    proc = MagicMock()
    proc.info = {"pid": pid, "cmdline": cmdline}
    return proc


# ---------------------------------------------------------------------------
# find_stale_claude_pids
# ---------------------------------------------------------------------------


class TestFindStaleClaude:
    """Core detection logic — matching + exclusions."""

    def test_returns_matching_non_ancestor(self):
        """A process matching the claude pattern, not in ancestor chain, is returned."""
        from installer.flow.kill_stale import find_stale_claude_pids

        claude_pid = 9901
        other_pid = 9902  # non-claude

        procs = [
            _make_proc_info(claude_pid, ["/usr/bin/claude"]),
            _make_proc_info(other_pid, ["/usr/bin/sleep", "9999"]),
        ]

        with (
            patch("installer.flow.kill_stale.psutil.process_iter", return_value=procs),
            patch(
                "installer.flow.kill_stale._ancestor_pids", return_value={os.getpid()}
            ),
        ):
            result = find_stale_claude_pids()

        assert claude_pid in result
        assert other_pid not in result, "non-claude process must NOT be in kill list"

    def test_excludes_ancestor_claude_pid(self):
        """A claude process that IS in the ancestor chain is excluded."""
        from installer.flow.kill_stale import find_stale_claude_pids

        ancestor_pid = (
            1001  # simulates the running Claude Code that launched the wizard
        )
        other_claude_pid = 1002  # a separate Claude Code session

        procs = [
            _make_proc_info(ancestor_pid, ["/usr/local/bin/claude"]),
            _make_proc_info(other_claude_pid, ["/usr/local/bin/claude", "--session"]),
        ]

        with (
            patch("installer.flow.kill_stale.psutil.process_iter", return_value=procs),
            patch(
                "installer.flow.kill_stale._ancestor_pids",
                return_value={ancestor_pid, os.getpid()},
            ),
        ):
            result = find_stale_claude_pids()

        assert ancestor_pid not in result, "ancestor PID must be excluded"
        assert other_claude_pid in result

    def test_non_claude_process_excluded(self):
        """A process with no claude in cmdline is excluded even if pid is low."""
        from installer.flow.kill_stale import find_stale_claude_pids

        procs = [
            _make_proc_info(5555, ["/usr/bin/python3", "server.py"]),
            _make_proc_info(5556, ["/bin/bash"]),
            _make_proc_info(5557, ["/usr/bin/sleep", "100"]),
        ]

        with (
            patch("installer.flow.kill_stale.psutil.process_iter", return_value=procs),
            patch(
                "installer.flow.kill_stale._ancestor_pids", return_value={os.getpid()}
            ),
        ):
            result = find_stale_claude_pids()

        assert result == [], "no claude processes → empty kill list"

    def test_no_processes_returns_empty(self):
        from installer.flow.kill_stale import find_stale_claude_pids

        with (
            patch("installer.flow.kill_stale.psutil.process_iter", return_value=[]),
            patch(
                "installer.flow.kill_stale._ancestor_pids", return_value={os.getpid()}
            ),
        ):
            result = find_stale_claude_pids()

        assert result == []

    def test_env_override_matcher(self, monkeypatch: pytest.MonkeyPatch):
        """CPM_CLAUDE_CODE_CMDLINE_MATCHER overrides the default pattern."""
        from installer.flow.kill_stale import find_stale_claude_pids

        monkeypatch.setenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER", r"my-custom-claude")

        procs = [
            _make_proc_info(8801, ["/opt/my-custom-claude"]),
            _make_proc_info(8802, ["/usr/bin/claude"]),  # default pattern, NOT custom
        ]

        with (
            patch("installer.flow.kill_stale.psutil.process_iter", return_value=procs),
            patch(
                "installer.flow.kill_stale._ancestor_pids", return_value={os.getpid()}
            ),
        ):
            result = find_stale_claude_pids()

        assert 8801 in result
        assert 8802 not in result

    def test_three_procs_two_claude_one_ancestor(self):
        """3 mocked procs: 2 claude, 1 not — ancestor excluded → 1 in kill list.

        This is the canonical regression guard described in the spec.
        """
        from installer.flow.kill_stale import find_stale_claude_pids

        ancestor_pid = 2001
        other_claude_pid = 2002
        non_claude_pid = 2003

        procs = [
            _make_proc_info(ancestor_pid, ["/usr/bin/claude"]),
            _make_proc_info(other_claude_pid, ["/usr/bin/claude"]),
            _make_proc_info(non_claude_pid, ["/usr/bin/sleep", "60"]),
        ]

        with (
            patch("installer.flow.kill_stale.psutil.process_iter", return_value=procs),
            patch(
                "installer.flow.kill_stale._ancestor_pids",
                return_value={ancestor_pid, os.getpid()},
            ),
        ):
            result = find_stale_claude_pids()

        # Only 1 process — the non-ancestor claude
        assert result == [other_claude_pid]
        assert ancestor_pid not in result, "wizard's ancestor PID must be excluded"
        assert non_claude_pid not in result, (
            "non-claude process must NOT be in kill list"
        )

    def test_proc_access_denied_skipped(self):
        """Processes raising AccessDenied are silently skipped."""
        from installer.flow.kill_stale import find_stale_claude_pids

        bad_proc = MagicMock()
        bad_proc.info = {"pid": 7777, "cmdline": None}  # no cmdline → skipped

        good_proc = _make_proc_info(7778, ["/usr/bin/claude"])

        with (
            patch(
                "installer.flow.kill_stale.psutil.process_iter",
                return_value=[bad_proc, good_proc],
            ),
            patch(
                "installer.flow.kill_stale._ancestor_pids", return_value={os.getpid()}
            ),
        ):
            result = find_stale_claude_pids()

        assert 7778 in result
        assert 7777 not in result


# ---------------------------------------------------------------------------
# _kill_pid — SIGTERM + SIGKILL fallback
# ---------------------------------------------------------------------------


class TestKillPid:
    """Verify SIGTERM → SIGKILL flow."""

    def test_sigterm_sent_and_waits(self):
        """Happy path: SIGTERM, process exits within timeout."""
        from installer.flow.kill_stale import _kill_pid

        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0  # exits cleanly

        with patch("installer.flow.kill_stale.psutil.Process", return_value=mock_proc):
            _kill_pid(12345)

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
        mock_proc.wait.assert_called_once()

    def test_sigkill_sent_on_timeout(self):
        """SIGTERM times out → SIGKILL is sent."""
        import psutil as _psutil
        from installer.flow.kill_stale import _kill_pid

        mock_proc = MagicMock()
        mock_proc.wait.side_effect = _psutil.TimeoutExpired(12345, 5.0)

        with patch("installer.flow.kill_stale.psutil.Process", return_value=mock_proc):
            _kill_pid(12345)

        calls = mock_proc.send_signal.call_args_list
        assert call(signal.SIGTERM) in calls
        assert call(signal.SIGKILL) in calls

    def test_no_such_process_ignored(self):
        """Process already gone at kill time — no exception raised."""
        import psutil as _psutil
        from installer.flow.kill_stale import _kill_pid

        with patch(
            "installer.flow.kill_stale.psutil.Process",
            side_effect=_psutil.NoSuchProcess(99999),
        ):
            _kill_pid(99999)  # must not raise

    def test_no_real_processes_killed(self):
        """Confirm psutil.Process is always patched in tests — no actual kills."""
        from installer.flow.kill_stale import _kill_pid

        kill_calls: list[int] = []

        class _FakeProc:
            def __init__(self, pid: int) -> None:
                self.pid = pid

            def send_signal(self, sig: int) -> None:
                kill_calls.append(sig)

            def wait(self, timeout: float = 0) -> int:
                return 0

        with patch("installer.flow.kill_stale.psutil.Process", side_effect=_FakeProc):
            _kill_pid(11111)

        assert signal.SIGTERM in kill_calls
        # wait() returned 0 → no SIGKILL
        assert signal.SIGKILL not in kill_calls


# ---------------------------------------------------------------------------
# prompt_kill_stale_sessions — integration
# ---------------------------------------------------------------------------


class TestPromptKillStaleSessions:
    def _make_console(self) -> Console:
        return Console(file=MagicMock(), highlight=False, width=120)

    def test_no_sessions_silent(self):
        """No stale sessions → prompt never shown, kill never called."""
        from installer.flow.kill_stale import prompt_kill_stale_sessions

        console = self._make_console()

        with (
            patch("installer.flow.kill_stale.find_stale_claude_pids", return_value=[]),
            patch("installer.flow.kill_stale._kill_pid") as mock_kill,
        ):
            prompt_kill_stale_sessions(console)

        mock_kill.assert_not_called()

    def test_user_says_yes_kills_all(self):
        """User confirms → _kill_pid called for each matched PID."""
        from installer.flow.kill_stale import prompt_kill_stale_sessions

        console = self._make_console()
        pids = [3001, 3002]

        with (
            patch(
                "installer.flow.kill_stale.find_stale_claude_pids", return_value=pids
            ),
            patch("installer.flow.kill_stale.ask_yn", return_value=True),
            patch("installer.flow.kill_stale._kill_pid") as mock_kill,
        ):
            prompt_kill_stale_sessions(console)

        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(3001)
        mock_kill.assert_any_call(3002)

    def test_user_says_no_no_kills(self):
        """User declines → _kill_pid never called."""
        from installer.flow.kill_stale import prompt_kill_stale_sessions

        console = self._make_console()

        with (
            patch(
                "installer.flow.kill_stale.find_stale_claude_pids", return_value=[4001]
            ),
            patch("installer.flow.kill_stale.ask_yn", return_value=False),
            patch("installer.flow.kill_stale._kill_pid") as mock_kill,
        ):
            prompt_kill_stale_sessions(console)

        mock_kill.assert_not_called()
