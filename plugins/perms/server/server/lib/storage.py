"""Atomic read/write for Claude Code settings.json and settings.local.json files."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from server.lib.models import Permissions, SandboxConfig, SettingsFile

_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
_USER_LOCAL_SETTINGS = Path.home() / ".claude" / "settings.local.json"


def _settings_path(scope: str, project_dir: Path | None = None) -> Path:
    if scope == "project":
        base = project_dir or Path.cwd()
        return base / ".claude" / "settings.json"
    return _USER_SETTINGS


def _local_settings_path(scope: str, project_dir: Path | None = None) -> Path:
    """Return the settings.local.json path for the given scope."""
    if scope == "project":
        base = project_dir or Path.cwd()
        return base / ".claude" / "settings.local.json"
    return _USER_LOCAL_SETTINGS


def _parse_settings_file(path: Path, raw: dict[str, object]) -> SettingsFile:
    """Parse raw JSON dict into a SettingsFile, extracting permissions and sandbox."""
    perms_raw = raw.get("permissions", {})
    if not isinstance(perms_raw, dict):
        perms_raw = {}

    sandbox_raw = raw.get("sandbox", {})
    if not isinstance(sandbox_raw, dict):
        sandbox_raw = {}

    return SettingsFile(
        path=path,
        permissions=Permissions.from_dict(perms_raw),  # type: ignore[arg-type]
        sandbox=SandboxConfig.from_dict(sandbox_raw),
        raw={k: v for k, v in raw.items() if k not in ("permissions", "sandbox")},
    )


def load(scope: str = "user", project_dir: Path | None = None) -> SettingsFile:
    """Load a settings.json file, returning empty defaults if it doesn't exist."""
    path = _settings_path(scope, project_dir)
    if not path.exists():
        return SettingsFile(path=path)

    with path.open() as f:
        raw: dict[str, object] = json.load(f)

    return _parse_settings_file(path, raw)


def load_local(scope: str = "user", project_dir: Path | None = None) -> SettingsFile:
    """Load a settings.local.json file, returning empty defaults if it doesn't exist."""
    path = _local_settings_path(scope, project_dir)
    if not path.exists():
        return SettingsFile(path=path)

    with path.open() as f:
        raw: dict[str, object] = json.load(f)

    return _parse_settings_file(path, raw)


def is_sandbox_enabled(scope: str = "user", project_dir: Path | None = None) -> bool:
    """Check if sandbox mode is enabled by reading settings.local.json."""
    local = load_local(scope, project_dir)
    return local.sandbox.enabled


def resolve_target(target: str, scope: str = "user", project_dir: Path | None = None) -> str:
    """Resolve ``auto`` target to ``settings`` or ``sandbox`` based on settings.local.json.

    Returns ``settings`` or ``sandbox``.
    """
    if target in ("settings", "sandbox"):
        return target
    # target == "auto": detect
    if is_sandbox_enabled(scope, project_dir):
        return "sandbox"
    return "settings"


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write content to path via a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode: int | None = None
    if path.exists():
        original_mode = path.stat().st_mode
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        tmp.replace(path)
        if original_mode is not None:
            path.chmod(original_mode & 0o7777)
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
