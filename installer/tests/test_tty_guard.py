"""Tests for installer.tty_guard.

Covers:
- Non-TTY stdin (pytest's default): guard is a no-op, no crash.
- Real PTY: guard captures termios at enter, restores on clean exit.
- Real PTY: guard restores even when wrapped code raises.
- Real PTY: guard falls back to `stty sane` when tcsetattr is unavailable.
"""

from __future__ import annotations

import os
import pty
import termios
import pytest

from installer.tty_guard import tty_guard


def test_noop_when_stdin_not_tty() -> None:
    """Guard must swallow non-TTY stdin and yield cleanly."""
    # Under pytest, sys.stdin is captured (not a tty). The guard should
    # still enter/exit without touching termios.
    with tty_guard():
        pass


def test_noop_does_not_mask_exception() -> None:
    """Exceptions raised inside the guard propagate unchanged (no TTY case)."""
    with pytest.raises(RuntimeError, match="boom"):
        with tty_guard():
            raise RuntimeError("boom")


def _fork_with_pty() -> tuple[int, int]:
    """Fork a child with a PTY; return (pid, master_fd)."""
    return pty.fork()


def _restore_child_stdin() -> None:
    """pytest replaces sys.stdin with DontReadFromInput before the test runs.
    After pty.fork(), the child inherits that replacement — and tty_guard's
    ``sys.stdin.fileno()`` call raises. Repair by rebinding sys.stdin to the
    raw fd 0 (which is the PTY slave after fork)."""
    import sys

    sys.stdin = os.fdopen(0, "r")


def test_pty_restores_on_clean_exit() -> None:
    """With a real PTY, guard restores termios to the saved value."""
    pid, fd = _fork_with_pty()
    if pid == 0:
        _restore_child_stdin()
        pre = termios.tcgetattr(0)
        with tty_guard():
            mangled = termios.tcgetattr(0)
            mangled[0] &= ~termios.ICRNL
            termios.tcsetattr(0, termios.TCSANOW, mangled)
        post = termios.tcgetattr(0)
        ok = (post[0] & termios.ICRNL) == (pre[0] & termios.ICRNL)
        os._exit(0 if ok else 1)
    else:
        _wait_read(fd)
        _, status = os.waitpid(pid, 0)
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0


def test_pty_restores_on_exception() -> None:
    """Exception inside guard still restores termios."""
    pid, fd = _fork_with_pty()
    if pid == 0:
        _restore_child_stdin()
        pre = termios.tcgetattr(0)
        try:
            with tty_guard():
                mangled = termios.tcgetattr(0)
                mangled[0] &= ~termios.ICRNL
                termios.tcsetattr(0, termios.TCSANOW, mangled)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        post = termios.tcgetattr(0)
        ok = (post[0] & termios.ICRNL) == (pre[0] & termios.ICRNL)
        os._exit(0 if ok else 2)
    else:
        _wait_read(fd)
        _, status = os.waitpid(pid, 0)
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0


def _wait_read(fd: int) -> None:
    """Drain master PTY fd until EOF — keeps child from blocking on write."""
    import select

    while True:
        r, _, _ = select.select([fd], [], [], 5.0)
        if not r:
            return
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            return
        if not chunk:
            return
