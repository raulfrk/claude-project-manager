"""Grant / revoke sandbox allowWrite paths and MCP wildcard rules for project paths."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.models import JsonValue, ProjConfig, ProjectMeta
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
            data: dict[str, JsonValue] = json.loads(path.read_text())
            sandbox = data.get("sandbox", {})
            if isinstance(sandbox, dict) and sandbox.get("enabled", False):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False




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
_ADDL_DIRS_ADDED_RE = re.compile(r"Additional directories added:\s*(\d+)")


def _parse_batch_setup_counts(result: str) -> dict[str, int]:
    """Extract sandbox_paths, mcp_rules, and additional_directories counts from batch_setup result string."""
    sandbox_m = _SANDBOX_ADDED_RE.search(result)
    mcp_m = _MCP_ADDED_RE.search(result)
    addl_m = _ADDL_DIRS_ADDED_RE.search(result)
    return {
        "sandbox_paths": int(sandbox_m.group(1)) if sandbox_m else 0,
        "mcp_rules": int(mcp_m.group(1)) if mcp_m else 0,
        "additional_directories": int(addl_m.group(1)) if addl_m else 0,
    }


def _compute_setup_paths(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    archive_destination: str | None = None,
    worktree_root_dir: str | None = None,
) -> list[str]:
    """Compute resolved absolute paths for sandbox allowWrite (writable repos + tracking + archive + worktree root)."""
    paths = []
    if cfg.permissions.projects_root:
        root = str(Path(cfg.permissions.projects_root).expanduser().resolve())
        paths.append(root)
    else:
        for repo in meta.repos:
            if not repo.reference:
                paths.append(str(Path(repo.path).expanduser().resolve()))

    if cfg.permissions.tracking_root:
        tracking = str(Path(cfg.permissions.tracking_root).expanduser().resolve())
        # Containment check: skip if already under projects_root
        if not any(tracking.startswith(p + "/") or tracking == p for p in paths):
            paths.append(tracking)
    elif cfg.tracking_dir:
        paths.append(str(Path(cfg.tracking_dir).expanduser().resolve()))

    if archive_destination:
        archive = str(Path(archive_destination).expanduser().resolve())
        # Containment check: skip if already under projects_root
        if not any(archive.startswith(p + "/") or archive == p for p in paths):
            paths.append(archive)

    if cfg.worktree_integration and worktree_root_dir:
        wt_root = str(Path(worktree_root_dir).expanduser().resolve())
        if not any(wt_root.startswith(p + "/") or wt_root == p for p in paths):
            paths.append(wt_root)

    return paths


def setup_permissions(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    mcp_servers: list[str] | None = None,
    archive_destination: str | None = None,
    worktree_root_dir: str | None = None,
    batch_setup_fn: Callable[..., str] | None = None,
) -> dict[str, int]:
    """Add sandbox allowWrite paths + MCP wildcard rules via the perms batch_setup function.

    Computes the list of writable paths and MCP servers, then delegates to
    ``batch_setup_fn`` for the actual settings file write.  When no
    ``batch_setup_fn`` is provided, returns computed counts without applying
    (hooks dispatch to perms plugin).

    Computed paths are also passed as ``additional_directories`` so the perms
    plugin can write them to ``permissions.additionalDirectories`` for permanent
    project directory access.

    Returns a dict with counts: {"sandbox_paths": N, "mcp_rules": N, "additional_directories": N}.
    Idempotent.
    """
    paths = _compute_setup_paths(meta, cfg, archive_destination=archive_destination, worktree_root_dir=worktree_root_dir)
    servers = mcp_servers or []

    if not paths and not servers:
        return {"sandbox_paths": 0, "mcp_rules": 0, "additional_directories": 0}

    if batch_setup_fn is not None:
        result = batch_setup_fn(
            paths=paths, mcp_servers=servers, additional_directories=paths,
        )
        return _parse_batch_setup_counts(result)

    # No batch_fn — return computed data; hooks dispatch to perms plugin
    return {
        "sandbox_paths": len(paths),
        "mcp_rules": len(servers),
        "additional_directories": len(paths),
    }


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
    if cfg.permissions.projects_root:
        paths.add(str(Path(cfg.permissions.projects_root).expanduser().resolve()).rstrip("/"))
    else:
        for repo in meta.repos:
            if not repo.reference:
                paths.add(str(Path(repo.path).expanduser().resolve()).rstrip("/"))
    if cfg.permissions.tracking_root:
        tracking = str(Path(cfg.permissions.tracking_root).expanduser().resolve()).rstrip("/")
        if not any(tracking.startswith(p + "/") or tracking == p for p in paths):
            paths.add(tracking)
    elif cfg.tracking_dir:
        paths.add(str(Path(cfg.tracking_dir).expanduser().resolve()).rstrip("/"))
    return paths


_SANDBOX_REMOVED_RE = re.compile(r"sandbox paths removed:\s*(\d+)")
_MCP_REMOVED_RE = re.compile(r"MCP rules removed:\s*(\d+)")
_ADDL_DIRS_REMOVED_RE = re.compile(r"additional directories removed:\s*(\d+)")


def _parse_batch_revoke_counts(result: str) -> dict[str, int]:
    """Extract sandbox_paths, mcp_rules, and additional_directories counts from batch_revoke result string."""
    sandbox_m = _SANDBOX_REMOVED_RE.search(result)
    mcp_m = _MCP_REMOVED_RE.search(result)
    addl_m = _ADDL_DIRS_REMOVED_RE.search(result)
    return {
        "sandbox_paths": int(sandbox_m.group(1)) if sandbox_m else 0,
        "mcp_rules": int(mcp_m.group(1)) if mcp_m else 0,
        "additional_directories": int(addl_m.group(1)) if addl_m else 0,
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
    ``batch_revoke_fn`` is provided, returns computed counts without applying
    (hooks dispatch to perms plugin).

    Also removes matching ``additional_directories`` entries.

    MCP wildcard rules are only removed when ``mcp_servers`` is explicitly
    provided, because they are shared across projects.

    Returns a dict with counts: {"sandbox_paths": N, "mcp_rules": N, "additional_directories": N}.
    Idempotent -- removing non-existent rules is a no-op.
    """
    # Compute sandbox paths to remove (writable repos + tracking dir)
    paths = list(_collect_sandbox_write_paths(meta, cfg))

    # MCP servers to remove (only when explicitly provided)
    servers = mcp_servers or []

    if not paths and not servers:
        return {"sandbox_paths": 0, "mcp_rules": 0, "additional_directories": 0}

    if batch_revoke_fn is not None:
        result = batch_revoke_fn(
            paths=paths, mcp_servers=servers, additional_directories=paths,
        )
        return _parse_batch_revoke_counts(result)

    # No batch_fn — return computed data; hooks dispatch to perms plugin
    return {
        "sandbox_paths": len(paths),
        "mcp_rules": len(servers),
        "additional_directories": len(paths),
    }


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
        worktree_root_dir: str | None = None,
    ) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        name = state.resolve_project(project_name)
        if not name:
            return json.dumps({"error": "No active project.", "success": False})
        if name not in index.projects:
            return json.dumps({"error": f"Project '{name}' not found.", "success": False})
        meta = storage.load_meta(cfg, name)

        # Collect paths (writable repos + tracking dir)
        paths = []
        for repo in meta.repos:
            if not repo.reference:
                paths.append(str(Path(repo.path).expanduser().resolve()))
        if cfg.tracking_dir:
            tracking = str(Path(cfg.tracking_dir).expanduser().resolve())
            if tracking not in paths:
                paths.append(tracking)

        counts = setup_permissions(
            meta,
            cfg,
            mcp_servers=mcp_servers or [],
            archive_destination=archive_destination,
            worktree_root_dir=worktree_root_dir,
        )
        total = sum(counts.values())
        return json.dumps({
            "result": "success",
            "project_name": name,
            "total": total,
            "counts": counts,
            "paths": paths,
            "mcp_servers": mcp_servers or [],
        })

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
            return json.dumps({"error": "No active project.", "success": False})
        if name not in index.projects:
            return json.dumps({"error": f"Project '{name}' not found.", "success": False})
        meta = storage.load_meta(cfg, name)

        # Collect paths (writable repos + tracking dir)
        paths = []
        for repo in meta.repos:
            if not repo.reference:
                paths.append(str(Path(repo.path).expanduser().resolve()))
        if cfg.tracking_dir:
            tracking = str(Path(cfg.tracking_dir).expanduser().resolve())
            if tracking not in paths:
                paths.append(tracking)

        counts = revoke_all_permissions(meta, cfg, mcp_servers=mcp_servers)
        total = sum(counts.values())
        return json.dumps({
            "result": "success",
            "project_name": name,
            "total": total,
            "counts": counts,
            "paths": paths,
            "mcp_servers": mcp_servers or [],
        })
