"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def get_claude_session_key() -> str:
    raise NotImplementedError


def read_active(file: Path, session_key: str | None = None) -> str | None:
    raise NotImplementedError


def write_active(file: Path, name: str, session_key: str | None = None) -> None:
    raise NotImplementedError


def clear_active(file: Path, session_key: str | None = None) -> None:
    raise NotImplementedError
