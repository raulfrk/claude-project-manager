"""Grant / revoke sandbox allowWrite paths and MCP wildcard rules for project paths."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectMeta
from server.lib.perms_helpers import project_dirs_from_meta
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ── Local settings path constants and sandbox detection ───────────────────────

_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
_USER_LOCAL_SETTINGS = Path.home() / ".claude" / "settings.local.json"


def _is_sandbox_enabled(
    project_dir: Path | None = None,
    project_dirs: list[Path] | None = None,
) -> bool:
    """Check if sandbox mode is enabled in user-level or project-level settings.local.json."""
    paths = [_USER_LOCAL_SETTINGS]
    if project_dirs:
        for d in project_dirs:
            paths.append(Path(d) / ".claude" / "settings.local.json")
    elif project_dir:
        paths.append(Path(project_dir) / ".claude" / "settings.local.json")
    for path in paths:
        if not path.exists():
            continue
        try:
            data: dict[str, object] = json.loads(path.read_text())
            sandbox = data.get("sandbox", {})
            if isinstance(sandbox, dict) and sandbox.get("enabled", False):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _effective_settings_path(project_dir: Path | None = None) -> Path:
    """Return settings.json or settings.local.json depending on sandbox mode."""
    if _is_sandbox_enabled(project_dir):
        return _USER_LOCAL_SETTINGS
    return _USER_SETTINGS


# ── Settings I/O ──────────────────────────────────────────────────────────────


def _load_settings(project_dir: Path | None = None) -> dict[str, object]:
    path = _effective_settings_path(project_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())  # type: ignore[return-value]


def _save_settings(data: dict[str, object], project_dir: Path | None = None) -> None:
    path = _effective_settings_path(project_dir)
    storage.atomic_write_json(path, data)


# ── Path helpers ───────────────────────────────────────────────────────────────


def collect_paths(
    meta: ProjectMeta,
    cfg: ProjConfig,
    worktree_base_paths: list[str] | None = None,
) -> list[str]:
    """Collect all project-related paths.

    Includes all registered project repo paths, the tracking directory (if set),
    and when worktree_integration is enabled, any base-repo paths passed via
    ``worktree_base_paths`` that are not already covered.
    """
    paths: list[str] = [repo.path for repo in meta.repos]

    if cfg.tracking_dir:
        abs_tracking = str(Path(cfg.tracking_dir).expanduser().resolve())
        if abs_tracking not in paths:
            paths.append(abs_tracking)

    if cfg.worktree_integration and worktree_base_paths:
        for path in worktree_base_paths:
            if path not in paths:
                paths.append(path)

    return paths


def _mcp_allow_entry(server_name: str) -> str:
    return f"mcp__{server_name}__*"


# ── Sandbox-aware helpers ──────────────────────────────────────────────────────


def _ensure_sandbox_section(data: dict[str, object]) -> dict[str, object]:
    """Ensure ``sandbox.filesystem.allowWrite`` path exists in the data dict."""
    sandbox = data.get("sandbox", {})
    if not isinstance(sandbox, dict):
        sandbox = {}
    fs = sandbox.get("filesystem", {})
    if not isinstance(fs, dict):
        fs = {}
    if "allowWrite" not in fs:
        fs["allowWrite"] = []
    sandbox["filesystem"] = fs
    data["sandbox"] = sandbox
    return data


def _add_sandbox_write_path(data: dict[str, object], abs_path: str) -> bool:
    """Add a path to sandbox.filesystem.allowWrite. Returns True if added."""
    data = _ensure_sandbox_section(data)
    sandbox = data["sandbox"]
    assert isinstance(sandbox, dict)
    fs = sandbox["filesystem"]
    assert isinstance(fs, dict)
    aw = fs["allowWrite"]
    assert isinstance(aw, list)
    clean = abs_path.rstrip("/")
    if clean not in aw:
        aw.append(clean)
        return True
    return False


def _remove_sandbox_write_path(data: dict[str, object], abs_path: str) -> bool:
    """Remove a path from sandbox.filesystem.allowWrite. Returns True if removed."""
    sandbox = data.get("sandbox")
    if not isinstance(sandbox, dict):
        return False
    fs = sandbox.get("filesystem")
    if not isinstance(fs, dict):
        return False
    aw = fs.get("allowWrite")
    if not isinstance(aw, list):
        return False
    clean = abs_path.rstrip("/")
    if clean in aw:
        aw.remove(clean)
        return True
    return False


# ── Setup (one-shot atomic write) ─────────────────────────────────────────────


def _apply_mcp_rules(
    servers: list[str],
    allow_set: set[str],
    new_entries: list[str],
) -> int:
    """Add MCP wildcard allow rules. Returns count added."""
    count = 0
    for server in servers:
        entry = _mcp_allow_entry(server)
        if entry not in allow_set:
            new_entries.append(entry)
            allow_set.add(entry)
            count += 1
    return count


_SANDBOX_ADDED_RE = re.compile(r"Sandbox paths added:\s*(\d+)")
_MCP_ADDED_RE = re.compile(r"MCP rules added:\s*(\d+)")


def _parse_batch_setup_counts(result: str) -> dict[str, int]:
    """Extract sandbox_paths and mcp_rules counts from batch_setup result string."""
    sandbox_m = _SANDBOX_ADDED_RE.search(result)
    mcp_m = _MCP_ADDED_RE.search(result)
    return {
        "sandbox_paths": int(sandbox_m.group(1)) if sandbox_m else 0,
        "mcp_rules": int(mcp_m.group(1)) if mcp_m else 0,
    }


def _compute_setup_paths(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    archive_destination: str | None = None,
) -> list[str]:
    """Compute resolved absolute paths for sandbox allowWrite (writable repos + tracking + archive)."""
    paths: list[str] = []
    for repo in meta.repos:
        if not repo.reference:
            paths.append(str(Path(repo.path).expanduser().resolve()))
    if cfg.tracking_dir:
        paths.append(str(Path(cfg.tracking_dir).expanduser().resolve()))
    if archive_destination:
        paths.append(str(Path(archive_destination).expanduser().resolve()))
    return paths


def setup_permissions(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    mcp_servers: list[str] | None = None,
    archive_destination: str | None = None,
    batch_setup_fn: Callable[..., str] | None = None,
) -> dict[str, int]:
    """Add sandbox allowWrite paths + MCP wildcard rules via the perms batch_setup function.

    Computes the list of writable paths and MCP servers, then delegates to
    ``batch_setup_fn`` for the actual settings file write.  When no
    ``batch_setup_fn`` is provided, falls back to a local implementation
    using the private helpers in this module.

    Returns a dict with counts: {"sandbox_paths": N, "mcp_rules": N}.
    All zero means the file was not written (all rules already present).
    Idempotent.
    """
    paths = _compute_setup_paths(meta, cfg, archive_destination=archive_destination)
    servers = mcp_servers or []

    if not paths and not servers:
        return {"sandbox_paths": 0, "mcp_rules": 0}

    if batch_setup_fn is not None:
        result = batch_setup_fn(paths=paths, mcp_servers=servers)
        return _parse_batch_setup_counts(result)

    # Fallback: local implementation using private helpers
    return _setup_permissions_local(meta, cfg, paths=paths, mcp_servers=servers)


def _setup_permissions_local(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    paths: list[str],
    mcp_servers: list[str],
) -> dict[str, int]:
    """Local fallback when no batch_setup_fn is provided."""
    project_dirs = project_dirs_from_meta(meta)
    project_dir = project_dirs[0] if project_dirs else None
    sandbox_mode = _is_sandbox_enabled(project_dirs=project_dirs)
    data = _load_settings(project_dir)
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        allow = []
    allow_set: set[str] = set(allow)

    new_entries: list[str] = []
    counts = {"sandbox_paths": 0, "mcp_rules": 0}

    if sandbox_mode:
        data = _ensure_sandbox_section(data)
        for abs_path in paths:
            if _add_sandbox_write_path(data, abs_path):
                counts["sandbox_paths"] += 1

    if mcp_servers:
        counts["mcp_rules"] = _apply_mcp_rules(mcp_servers, allow_set, new_entries)

    if new_entries or sum(counts.values()) > 0:
        if new_entries:
            allow.extend(new_entries)
            perms["allow"] = allow
            data["permissions"] = perms
        _save_settings(data, project_dir)

    return counts


# ── Revoke all (inverse of setup_permissions) ─────────────────────────────────


def _collect_all_allow_rules(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    mcp_servers: list[str] | None = None,
) -> set[str]:
    """Derive MCP wildcard rules for revocation.

    Only MCP wildcard rules are collected here. Sandbox paths are handled
    separately.
    MCP rules are only included when ``mcp_servers`` is explicitly provided,
    because MCP wildcard rules (e.g. ``mcp__plugin_proj_proj__*``) are shared
    across all projects and should not be revoked on single-project archive
    unless explicitly requested.
    """
    rules: set[str] = set()

    # MCP wildcard rules — only when explicitly provided
    if mcp_servers:
        for server in mcp_servers:
            rules.add(_mcp_allow_entry(server))

    return rules


def _collect_sandbox_write_paths(meta: ProjectMeta, cfg: ProjConfig) -> set[str]:
    """Derive the sandbox.filesystem.allowWrite paths that setup_permissions would create."""
    paths: set[str] = set()
    for repo in meta.repos:
        if not repo.reference:
            paths.add(str(Path(repo.path).expanduser().resolve()).rstrip("/"))
    if cfg.tracking_dir:
        paths.add(str(Path(cfg.tracking_dir).expanduser().resolve()).rstrip("/"))
    return paths


_SANDBOX_REMOVED_RE = re.compile(r"sandbox paths removed:\s*(\d+)")
_MCP_REMOVED_RE = re.compile(r"MCP rules removed:\s*(\d+)")


def _parse_batch_revoke_counts(result: str) -> dict[str, int]:
    """Extract sandbox_paths and mcp_rules counts from batch_revoke result string."""
    sandbox_m = _SANDBOX_REMOVED_RE.search(result)
    mcp_m = _MCP_REMOVED_RE.search(result)
    return {
        "sandbox_paths": int(sandbox_m.group(1)) if sandbox_m else 0,
        "mcp_rules": int(mcp_m.group(1)) if mcp_m else 0,
    }


def revoke_all_permissions(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    mcp_servers: list[str] | None = None,
    batch_revoke_fn: Callable[..., str] | None = None,
) -> dict[str, int]:
    """Remove MCP wildcard rules from permissions.allow and sandbox allowWrite paths.

    Computes which paths and MCP servers to remove, then delegates to
    ``batch_revoke_fn`` for the actual settings file I/O.  When no
    ``batch_revoke_fn`` is provided, falls back to a local implementation.

    MCP wildcard rules are only removed when ``mcp_servers`` is explicitly
    provided, because they are shared across projects.

    Returns a dict with counts: {"sandbox_paths": N, "mcp_rules": N}.
    Idempotent -- removing non-existent rules is a no-op.
    """
    # Compute sandbox paths to remove (writable repos + tracking dir)
    paths = list(_collect_sandbox_write_paths(meta, cfg))

    # MCP servers to remove (only when explicitly provided)
    servers = mcp_servers or []

    if not paths and not servers:
        return {"sandbox_paths": 0, "mcp_rules": 0}

    if batch_revoke_fn is not None:
        result = batch_revoke_fn(paths=paths, mcp_servers=servers)
        return _parse_batch_revoke_counts(result)

    # Fallback: local implementation using private helpers
    return _revoke_all_permissions_local(meta, cfg, paths=paths, mcp_servers=servers)


def _revoke_all_permissions_local(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    paths: list[str],
    mcp_servers: list[str],
) -> dict[str, int]:
    """Local fallback when no batch_revoke_fn is provided."""
    project_dirs = project_dirs_from_meta(meta)
    project_dir = project_dirs[0] if project_dirs else None
    sandbox_mode = _is_sandbox_enabled(project_dirs=project_dirs)
    data = _load_settings(project_dir)
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        allow = []

    counts = {"sandbox_paths": 0, "mcp_rules": 0}

    # Remove MCP wildcard rules from permissions.allow
    to_remove = _collect_all_allow_rules(meta, cfg, mcp_servers=mcp_servers)
    new_allow = [r for r in allow if r not in to_remove]
    counts["mcp_rules"] = len(allow) - len(new_allow)

    # Remove sandbox write paths
    if sandbox_mode:
        for p in paths:
            if _remove_sandbox_write_path(data, p):
                counts["sandbox_paths"] += 1

    total = sum(counts.values())
    if total > 0:
        perms["allow"] = new_allow
        data["permissions"] = perms
        _save_settings(data, project_dir)

    return counts


# ── MCP tool registration ──────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register proj_setup_permissions and proj_revoke_all_permissions tools with the MCP app."""

    @app.tool(
        description=(
            "Grant sandbox allowWrite paths + MCP wildcard rules for a project "
            "in one atomic write. Idempotent. "
            "Automatically detects sandbox mode and writes to settings.local.json if enabled. "
            "Writable repo paths and the tracking dir are added to sandbox.filesystem.allowWrite. "
            "mcp_servers is a list of server names to add wildcard allow rules for "
            "(e.g. ['plugin_proj_proj', 'plugin_perms_perms', 'trello'])."
        )
    )
    def proj_setup_permissions(
        project_name: str | None = None,
        mcp_servers: list[str] | None = None,
        archive_destination: str | None = None,
    ) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        if name not in index.projects:
            return f"Project '{name}' not found."
        meta = storage.load_meta(cfg, name)
        counts = setup_permissions(
            meta,
            cfg,
            mcp_servers=mcp_servers or [],
            archive_destination=archive_destination,
        )
        total = sum(counts.values())
        if total == 0:
            return f"All permission rules already up to date for '{name}'."
        parts = []
        if counts["sandbox_paths"]:
            parts.append(f"{counts['sandbox_paths']} sandbox path(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        return f"Added {total} rule(s) for '{name}': {', '.join(parts)}."

    @app.tool(
        description=(
            "Remove MCP wildcard rules and sandbox write paths for a project. "
            "Inverse of proj_setup_permissions. "
            "MCP wildcard rules are only removed when mcp_servers is provided, "
            "because they are shared across projects. "
            "Automatically called by proj_archive. Idempotent. "
            "Automatically detects sandbox mode."
        )
    )
    def proj_revoke_all_permissions(
        project_name: str | None = None,
        mcp_servers: list[str] | None = None,
    ) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        if name not in index.projects:
            return f"Project '{name}' not found."
        meta = storage.load_meta(cfg, name)
        counts = revoke_all_permissions(meta, cfg, mcp_servers=mcp_servers)
        total = sum(counts.values())
        if total == 0:
            return f"No permission rules found for '{name}' -- nothing to remove."
        parts = []
        if counts["sandbox_paths"]:
            parts.append(f"{counts['sandbox_paths']} sandbox path(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        return f"Removed {total} rule(s) for '{name}': {', '.join(parts)}."
