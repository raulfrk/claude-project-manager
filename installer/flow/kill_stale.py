# installer/flow/kill_stale.py
"""Detect and prompt to kill stale Claude Code sessions after install/reinstall.

After new plugin code lands on disk, already-running Claude Code processes keep
executing old MCP subprocess code until the outer Claude Code process restarts.
This step detects those sessions and offers to kill them.

Matcher regex is identical to plugins/_shared/session_key/session_key.py
(``_DEFAULT_MATCHER`` / ``CPM_CLAUDE_CODE_CMDLINE_MATCHER`` env override) so
both subsystems stay in sync.
"""

from __future__ import annotations

import os
import re
import signal

import psutil
from rich.console import Console

from installer.flow.yn import ask_yn

# Reuse the exact matcher from plugins/_shared/session_key/session_key.py.
# If that default ever changes, update here too (and vice-versa).
_DEFAULT_MATCHER: re.Pattern[str] = re.compile(r"(?:^|/)claude(?:\s|$)")
_KILL_TIMEOUT_S: float = 5.0


def _get_matcher() -> re.Pattern[str]:
    """Return cmdline matcher, respecting CPM_CLAUDE_CODE_CMDLINE_MATCHER override."""
    custom = os.getenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER")
    if custom:
        return re.compile(custom)
    return _DEFAULT_MATCHER


def _cmdline_str(parts: list[str]) -> str:
    return " ".join(parts)


def _ancestor_pids() -> set[int]:
    """Return set of PIDs in the current process's parent chain (inclusive of self)."""
    pids: set[int] = {os.getpid()}
    try:
        proc = psutil.Process()
        for ancestor in proc.parents():
            pids.add(ancestor.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return pids


def find_stale_claude_pids() -> list[int]:
    """Scan running processes and return PIDs of other Claude Code sessions.

    Excludes:
    - Processes whose cmdline doesn't match the Claude Code matcher regex.
    - Any PID in the current process's ancestor chain (to avoid self-kill).
    """
    matcher = _get_matcher()
    excluded = _ancestor_pids()
    matches: list[int] = []
    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                pid = proc.info["pid"]
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue
                if pid in excluded:
                    continue
                if matcher.search(_cmdline_str(cmdline)):
                    matches.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:  # noqa: BLE001
        pass
    return matches


def _kill_pid(pid: int) -> None:
    """SIGTERM a process, then SIGKILL after _KILL_TIMEOUT_S if still alive."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=_KILL_TIMEOUT_S)
    except psutil.TimeoutExpired:
        try:
            proc.send_signal(signal.SIGKILL)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def prompt_kill_stale_sessions(console: Console) -> None:
    """Detect stale Claude Code sessions and offer to kill them.

    Runs after install / reinstall completes. If no other sessions are found,
    returns silently. On user confirmation, SIGTERMs each matched PID with a
    SIGKILL fallback after _KILL_TIMEOUT_S.
    """
    pids = find_stale_claude_pids()
    if not pids:
        return

    n = len(pids)
    label = "session" if n == 1 else "sessions"
    prompt = (
        f"{n} other Claude Code {label} running with cached plugin versions. "
        f"Kill {'it' if n == 1 else 'them'} so {'it' if n == 1 else 'they'} "
        f"pick up the new install?"
    )
    if not ask_yn(prompt, default=False, console=console):
        return

    for pid in pids:
        _kill_pid(pid)

    console.print(f"[green]✓[/] Sent kill signal to {n} Claude Code {label}.")
