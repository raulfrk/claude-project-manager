"""Atomic read/write for ~/.claude/settings.json (sandbox-mode only)."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import tempfile
from pathlib import Path

from server.lib.models import SettingsFile

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def load() -> SettingsFile:
    """Load ~/.claude/settings.json, returning empty defaults if missing or corrupt."""
    if not SETTINGS_PATH.exists():
        return SettingsFile(path=SETTINGS_PATH)

    try:
        with SETTINGS_PATH.open() as f:
            raw: dict[str, object] = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse %s: %s — returning defaults", SETTINGS_PATH, exc)
        return SettingsFile(path=SETTINGS_PATH)

    return SettingsFile.from_dict(SETTINGS_PATH, raw)


def save(settings: SettingsFile) -> None:
    """Atomically write settings to disk, creating parent dirs if needed."""
    data = settings.to_dict()
    content = json.dumps(data, indent=2) + "\n"
    _atomic_write(settings.path, content)


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write content to path via a temp file in the same directory.

    Resolves symlinks before writing to avoid replacing symlinks with regular files.
    """
    # Resolve symlinks so temp file lands in the real target directory
    real_path = path.resolve()
    real_path.parent.mkdir(parents=True, exist_ok=True)

    original_mode: int | None = None
    if real_path.exists():
        original_mode = real_path.stat().st_mode

    fd, tmp_str = tempfile.mkstemp(dir=real_path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        tmp.replace(real_path)
        if original_mode is not None:
            real_path.chmod(stat.S_IMODE(original_mode))
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def allow_entries_for_path(abs_path: str) -> list[str]:
    """Return the Edit allow rule for an absolute path."""
    clean = abs_path.rstrip("/")
    if not clean.startswith("/"):
        msg = f"Expected absolute path, got: {abs_path!r}"
        raise ValueError(msg)
    prefix = f"//{clean.lstrip('/')}"
    return [f"Edit({prefix}/**)"]


def skill_allow_entry(prefix: str) -> str:
    """Return the wildcard allow rule for a skill prefix.

    E.g. prefix="proj" -> "Skill(proj:*)"
    """
    if not prefix:
        msg = "prefix must not be empty"
        raise ValueError(msg)
    if "*" in prefix or "(" in prefix or ")" in prefix:
        msg = f"prefix must not contain '*', '(' or ')': {prefix!r}"
        raise ValueError(msg)
    return f"Skill({prefix}:*)"


def mcp_allow_entry(server_name: str) -> str:
    """Return the wildcard allow rule for an MCP server.

    E.g. server_name="plugin_proj_proj" -> "mcp__plugin_proj_proj__*"
    """
    if not server_name:
        msg = "server_name must not be empty"
        raise ValueError(msg)
    if "__" in server_name or "*" in server_name:
        msg = f"server_name must not contain '__' or '*': {server_name!r}"
        raise ValueError(msg)
    return f"mcp__{server_name}__*"
