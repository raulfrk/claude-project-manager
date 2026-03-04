"""Atomic read/write for Claude Code settings.json files."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from server.lib.models import Permissions, SettingsFile

_USER_SETTINGS = Path.home() / ".claude" / "settings.json"


def _settings_path(scope: str, project_dir: Path | None = None) -> Path:
    if scope == "project":
        base = project_dir or Path.cwd()
        return base / ".claude" / "settings.json"
    return _USER_SETTINGS


def load(scope: str = "user", project_dir: Path | None = None) -> SettingsFile:
    """Load a settings.json file, returning empty defaults if it doesn't exist."""
    path = _settings_path(scope, project_dir)
    if not path.exists():
        return SettingsFile(path=path)

    with path.open() as f:
        raw: dict[str, object] = json.load(f)

    perms_raw = raw.get("permissions", {})
    if not isinstance(perms_raw, dict):
        perms_raw = {}

    return SettingsFile(
        path=path,
        permissions=Permissions.from_dict(perms_raw),  # type: ignore[arg-type]  # dict[str,object] narrowed but pyright can't verify
        raw={k: v for k, v in raw.items() if k != "permissions"},
    )


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write content to path via a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        tmp.replace(path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def save(settings: SettingsFile) -> None:
    """Atomically write settings to disk, creating parent dirs if needed."""
    data = settings.to_dict()
    content = json.dumps(data, indent=2) + "\n"
    _atomic_write(settings.path, content)


def allow_entries_for_path(abs_path: str) -> list[str]:
    """Return the Read and Edit allow rules for an absolute path."""
    clean = abs_path.rstrip("/")
    if not clean.startswith("/"):
        msg = f"Expected absolute path, got: {abs_path!r}"
        raise ValueError(msg)
    # Double-slash prefix required by Claude Code for absolute paths
    prefix = f"//{clean.lstrip('/')}"
    return [f"Read({prefix}/**)", f"Edit({prefix}/**)"]


def mcp_allow_entry(server_name: str) -> str:
    """Return the wildcard allow rule for an MCP server.

    E.g. server_name="proj" → "mcp__proj__*"
    """
    if not server_name:
        msg = "server_name must not be empty"
        raise ValueError(msg)
    return f"mcp__{server_name}__*"
