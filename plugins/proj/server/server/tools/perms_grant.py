"""Grant / revoke sandbox allowWrite paths and MCP wildcard rules for project paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectMeta
from server.lib.perms_helpers import (
    _WORKTREE_CONFIG,
    effective_settings_path,
    is_sandbox_enabled,
    project_dirs_from_meta,
)
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


# ── Settings I/O ──────────────────────────────────────────────────────────────


def _load_settings(project_dir: Path | None = None) -> dict[str, object]:
    path = effective_settings_path(project_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())  # type: ignore[return-value]


def _save_settings(data: dict[str, object], project_dir: Path | None = None) -> None:
    path = effective_settings_path(project_dir)
    storage.atomic_write_json(path, data)


# ── Path helpers ───────────────────────────────────────────────────────────────


def collect_paths(meta: ProjectMeta, cfg: ProjConfig) -> list[str]:
    """Collect all project-related paths.

    Includes all registered project repo paths, the tracking directory (if set),
    and when worktree_integration is enabled, any base-repo paths from
    ``~/.claude/worktree.yaml`` that are not already covered.
    """
    paths: list[str] = [repo.path for repo in meta.repos]

    if cfg.tracking_dir:
        abs_tracking = str(Path(cfg.tracking_dir).expanduser().resolve())
        if abs_tracking not in paths:
            paths.append(abs_tracking)

    if cfg.worktree_integration and _WORKTREE_CONFIG.exists():
        try:
            wt_data: dict[str, object] = yaml.safe_load(_WORKTREE_CONFIG.read_text()) or {}
            base_repos_raw = wt_data.get("base_repos", [])
            if isinstance(base_repos_raw, list):
                for repo in base_repos_raw:
                    if isinstance(repo, dict):
                        path = repo.get("path", "")
                        if isinstance(path, str) and path and path not in paths:
                            paths.append(path)
        except Exception:  # noqa: BLE001
            pass  # Gracefully skip if worktree config is unavailable

    return paths


def _mcp_allow_entry(server_name: str) -> str:
    return f"mcp__{server_name}__*"


# Built-in tools that should always be allowed (read-only, no security risk)
_ALWAYS_ALLOWED_TOOLS: list[str] = ["Search"]


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


def _add_sandbox_deny_write_path(data: dict[str, object], abs_path: str) -> bool:
    """Add a path to sandbox.filesystem.denyWrite. Returns True if added."""
    data = _ensure_sandbox_section(data)
    sandbox = data["sandbox"]
    assert isinstance(sandbox, dict)
    fs = sandbox["filesystem"]
    assert isinstance(fs, dict)
    dw = fs.get("denyWrite")
    if not isinstance(dw, list):
        dw = []
        fs["denyWrite"] = dw
    clean = abs_path.rstrip("/")
    if clean not in dw:
        dw.append(clean)
        return True
    return False


def _remove_sandbox_deny_write_path(data: dict[str, object], abs_path: str) -> bool:
    """Remove a path from sandbox.filesystem.denyWrite. Returns True if removed."""
    sandbox = data.get("sandbox")
    if not isinstance(sandbox, dict):
        return False
    fs = sandbox.get("filesystem")
    if not isinstance(fs, dict):
        return False
    dw = fs.get("denyWrite")
    if not isinstance(dw, list):
        return False
    clean = abs_path.rstrip("/")
    if clean in dw:
        dw.remove(clean)
        return True
    return False


# ── Sensitive-path deny helpers ───────────────────────────────────────────────

_SENSITIVE_DENY_RULES: list[str] = [
    "Read(~/.ssh/**)",
    "Read(~/.gnupg/**)",
    "Read(~/.aws/**)",
]


def _add_sensitive_deny_rules(data: dict[str, object]) -> int:
    """Add permissions.deny entries for sensitive paths. Returns count added."""
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
    deny = perms.get("deny", [])
    if not isinstance(deny, list):
        deny = []
    deny_set: set[str] = set(deny)
    count = 0
    for rule in _SENSITIVE_DENY_RULES:
        if rule not in deny_set:
            deny.append(rule)
            deny_set.add(rule)
            count += 1
    if count:
        perms["deny"] = deny
        data["permissions"] = perms
    return count


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


def _apply_builtin_rules(
    allow_set: set[str],
    new_entries: list[str],
) -> int:
    """Add built-in tool allow rules. Returns count added."""
    count = 0
    for tool in _ALWAYS_ALLOWED_TOOLS:
        if tool not in allow_set:
            new_entries.append(tool)
            allow_set.add(tool)
            count += 1
    return count


def setup_permissions(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    mcp_servers: list[str] | None = None,
    archive_destination: str | None = None,
) -> dict[str, int]:
    """Add sandbox allowWrite paths, MCP wildcard rules, and built-in tool rules.

    Targets settings.local.json (sandbox mode) or settings.json (fallback).

    Writes:
    - sandbox.filesystem.allowWrite paths for writable repos, tracking dir,
      and archive destination (if provided)
    - sandbox.filesystem.denyWrite paths for reference repos (defense-in-depth)
    - permissions.deny entries for sensitive paths (~/.ssh, ~/.gnupg, ~/.aws)
    - MCP server wildcard rules in permissions.allow
    - Built-in tool rules in permissions.allow (e.g. Search)

    Returns a dict with counts: {"sandbox_paths": N, "deny_write_paths": N,
    "sensitive_deny_rules": N, "mcp_rules": N, "builtin_rules": N}.
    All zero means the file was not written (all rules already present).
    Idempotent.
    """
    project_dirs = project_dirs_from_meta(meta)
    project_dir = project_dirs[0] if project_dirs else None
    sandbox_mode = is_sandbox_enabled(project_dirs=project_dirs)
    data = _load_settings(project_dir)
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        allow = []
    allow_set: set[str] = set(allow)

    new_entries: list[str] = []
    counts = {"sandbox_paths": 0, "deny_write_paths": 0, "sensitive_deny_rules": 0, "mcp_rules": 0, "builtin_rules": 0}

    # Sandbox allowWrite paths for writable repos and tracking dir
    if sandbox_mode:
        data = _ensure_sandbox_section(data)
        for repo in meta.repos:
            abs_path = str(Path(repo.path).expanduser().resolve())
            if repo.reference:
                # Defense-in-depth: explicitly deny writes to reference repos
                if _add_sandbox_deny_write_path(data, abs_path):
                    counts["deny_write_paths"] += 1
            else:
                if _add_sandbox_write_path(data, abs_path):
                    counts["sandbox_paths"] += 1
        if cfg.tracking_dir:
            abs_tracking = str(Path(cfg.tracking_dir).expanduser().resolve())
            if _add_sandbox_write_path(data, abs_tracking):
                counts["sandbox_paths"] += 1

    # Sensitive path deny rules (always applied, not sandbox-specific)
    counts["sensitive_deny_rules"] = _add_sensitive_deny_rules(data)

    # MCP wildcard rules
    if mcp_servers:
        counts["mcp_rules"] = _apply_mcp_rules(mcp_servers, allow_set, new_entries)

    # Built-in tool rules (always allowed)
    counts["builtin_rules"] = _apply_builtin_rules(allow_set, new_entries)

    # Archive destination: only sandbox write path
    if archive_destination:
        abs_dest = str(Path(archive_destination).expanduser().resolve())
        if sandbox_mode:
            if _add_sandbox_write_path(data, abs_dest):
                counts["sandbox_paths"] += 1

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
    """Derive the full set of allow rules that setup_permissions would create.

    Only MCP wildcard rules are managed in permissions.allow now.
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


def _collect_sandbox_deny_write_paths(meta: ProjectMeta) -> set[str]:
    """Derive the sandbox.filesystem.denyWrite paths for reference repos."""
    paths: set[str] = set()
    for repo in meta.repos:
        if repo.reference:
            paths.add(str(Path(repo.path).expanduser().resolve()).rstrip("/"))
    return paths


def revoke_all_permissions(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    mcp_servers: list[str] | None = None,
) -> dict[str, int]:
    """Remove MCP wildcard rules from permissions.allow, sandbox allowWrite and denyWrite paths.

    Inverse of setup_permissions. Only MCP rules + sandbox paths are managed now.
    MCP wildcard rules are only removed when ``mcp_servers`` is explicitly
    provided, because they are shared across projects.

    Note: sensitive path deny rules (permissions.deny for ~/.ssh, ~/.gnupg,
    ~/.aws) are NOT removed -- those are global safety rules.

    Returns a dict with counts: {"sandbox_paths": N, "deny_write_paths": N, "mcp_rules": N}.
    Idempotent -- removing non-existent rules is a no-op.
    """
    project_dirs = project_dirs_from_meta(meta)
    project_dir = project_dirs[0] if project_dirs else None
    sandbox_mode = is_sandbox_enabled(project_dirs=project_dirs)
    data = _load_settings(project_dir)
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        allow = []

    counts = {"sandbox_paths": 0, "deny_write_paths": 0, "mcp_rules": 0}

    # Remove MCP wildcard rules from permissions.allow
    to_remove = _collect_all_allow_rules(meta, cfg, mcp_servers=mcp_servers)
    new_allow = [r for r in allow if r not in to_remove]
    counts["mcp_rules"] = len(allow) - len(new_allow)

    # Remove sandbox write paths and deny-write paths for reference repos
    if sandbox_mode:
        for p in _collect_sandbox_write_paths(meta, cfg):
            if _remove_sandbox_write_path(data, p):
                counts["sandbox_paths"] += 1
        for p in _collect_sandbox_deny_write_paths(meta):
            if _remove_sandbox_deny_write_path(data, p):
                counts["deny_write_paths"] += 1

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
            "Reference repos are added to sandbox.filesystem.denyWrite (defense-in-depth). "
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
        if counts.get("deny_write_paths"):
            parts.append(f"{counts['deny_write_paths']} deny-write path(s)")
        if counts.get("sensitive_deny_rules"):
            parts.append(f"{counts['sensitive_deny_rules']} sensitive deny rule(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        if counts.get("builtin_rules"):
            parts.append(f"{counts['builtin_rules']} built-in tool rule(s)")
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
        if counts.get("deny_write_paths"):
            parts.append(f"{counts['deny_write_paths']} deny-write path(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        return f"Removed {total} rule(s) for '{name}': {', '.join(parts)}."
