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
from typing import Literal

import psutil
from rich.console import Console

from installer.flow.yn import ask_yn

# Reuse the exact matcher from plugins/_shared/session_key/session_key.py.
# If that default ever changes, update here too (and vice-versa).
_DEFAULT_MATCHER: re.Pattern[str] = re.compile(r"(?:^|/)claude(?:\s|$)")
_KILL_TIMEOUT_S: float = 5.0

KillStatus = Literal["killed", "timeout_killed", "not_found", "denied"]


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


def find_stale_claude_pids() -> list[tuple[int, str]]:
    """Scan running processes and return (pid, cmdline_preview) of other Claude Code sessions.

    Excludes:
    - Processes whose cmdline doesn't match the Claude Code matcher regex.
    - Any PID in the current process's ancestor chain (to avoid self-kill).
    """
    matcher = _get_matcher()
    excluded = _ancestor_pids()
    matches: list[tuple[int, str]] = []
    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                pid = proc.info["pid"]
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue
                if pid in excluded:
                    continue
                cmd_str = _cmdline_str(cmdline)
                if matcher.search(cmd_str):
                    matches.append((pid, cmd_str))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:  # noqa: BLE001
        pass
    return matches


def _kill_pid(pid: int) -> KillStatus:
    """SIGTERM a process, then SIGKILL after _KILL_TIMEOUT_S if still alive.

    Returns:
        "killed"         — SIGTERM sent and process exited within timeout
        "timeout_killed" — SIGTERM timed out, SIGKILL sent
        "not_found"      — process did not exist at kill time
        "denied"         — operation was denied (different uid, etc.)
    """
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return "not_found"
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=_KILL_TIMEOUT_S)
        return "killed"
    except psutil.TimeoutExpired:
        try:
            proc.send_signal(signal.SIGKILL)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return "timeout_killed"
    except psutil.NoSuchProcess:
        return "not_found"
    except psutil.AccessDenied:
        return "denied"


def prompt_kill_stale_sessions(console: Console) -> None:
    """Detect stale Claude Code sessions and offer to kill them.

    Runs after install / reinstall completes. If no other sessions are found,
    returns silently. On user confirmation, SIGTERMs each matched PID with a
    SIGKILL fallback after _KILL_TIMEOUT_S. Reports a breakdown of outcomes.
    """
    detected = find_stale_claude_pids()
    if not detected:
        return

    n = len(detected)

    # List detected PIDs before prompting so user can verify the set.
    console.print("[yellow]Detected stale Claude Code sessions:[/]")
    for pid, cmdline in detected:
        console.print(f"  pid {pid}: {cmdline[:80]}")

    label = "session" if n == 1 else "sessions"
    prompt = (
        f"{n} other Claude Code {label} running with cached plugin versions. "
        f"Kill {'it' if n == 1 else 'them'} so {'it' if n == 1 else 'they'} "
        f"pick up the new install?"
    )
    if not ask_yn(prompt, default=False, console=console):
        return

    statuses: list[KillStatus] = [_kill_pid(pid) for pid, _ in detected]

    killed = statuses.count("killed")
    timeout_killed = statuses.count("timeout_killed")
    not_found = statuses.count("not_found")
    denied = statuses.count("denied")

    total_killed = killed + timeout_killed

    parts: list[str] = []
    if total_killed > 0:
        sigkill_note = (
            f" ({timeout_killed} needed SIGKILL)" if timeout_killed > 0 else ""
        )
        parts.append(f"Killed {total_killed}{sigkill_note}")
    if not_found > 0:
        parts.append(f"{not_found} already exited")
    if denied > 0:
        parts.append(f"{denied} denied (different uid?)")

    summary = "; ".join(parts) if parts else "No sessions killed"
    console.print(f"[green]✓[/] {summary}.")
