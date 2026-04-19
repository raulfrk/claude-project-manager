# installer/flow/console.py
"""Shared Rich Console singleton for the installer flow layer."""

from __future__ import annotations

from rich.console import Console

_console: Console | None = None


def get_console() -> Console:
    """Return the shared Rich Console, creating it on first call."""
    global _console
    if _console is None:
        _console = Console()
    return _console


def reset_console() -> None:
    """Drop the cached console. For tests only."""
    global _console
    _console = None
