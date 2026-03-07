"""Grant / revoke Bash investigation-tool permissions for project paths."""

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
    project_dir_from_meta,
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


def _bash_entry(tool: str, abs_path: str) -> str:
    """Build a scoped Bash allow rule: ``Bash(grep //home/user/proj/**)``.

    The double-slash prefix is required by Claude Code for absolute paths.
    """
    prefix = f"//{abs_path.strip('/')}"
    return f"Bash({tool} {prefix}/**)"


def collect_paths(meta: ProjectMeta, cfg: ProjConfig) -> list[str]:
    """Collect all paths that should receive investigation-tool access.

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


# ── Path-rule helpers ──────────────────────────────────────────────────────────


def _path_allow_entries(abs_path: str) -> list[str]:
    """Return ``Read`` and ``Edit`` allow rules for an absolute path."""
    prefix = f"//{abs_path.strip('/')}"
    return [f"Read({prefix}/**)", f"Edit({prefix}/**)"]


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


# ── Grant / revoke ─────────────────────────────────────────────────────────────


def grant_investigation_tools(meta: ProjectMeta, cfg: ProjConfig) -> int:
    """Add scoped Bash allow rules for investigation tools.

    Idempotent — existing rules are not duplicated.

    Returns the number of new rules added.
    """
    paths = collect_paths(meta, cfg)
    tools = cfg.permissions.investigation_tools
    if not tools or not paths:
        return 0

    project_dirs = project_dirs_from_meta(meta)
    project_dir = project_dirs[0] if project_dirs else None
    data = _load_settings(project_dir)
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        allow = []

    allow_set: set[str] = set(allow)
    new_entries: list[str] = []
    for path in paths:
        for tool in tools:
            entry = _bash_entry(tool, path)
            if entry not in allow_set:
                new_entries.append(entry)
                allow_set.add(entry)

    if new_entries:
        allow.extend(new_entries)
        perms["allow"] = allow
        data["permissions"] = perms
        _save_settings(data, project_dir)

    return len(new_entries)


def revoke_investigation_tools(meta: ProjectMeta, cfg: ProjConfig) -> int:
    """Remove scoped Bash allow rules for investigation tools.

    Only removes rules that match the current tool list and project paths.
    Unrelated allow rules are never touched.
    Idempotent.

    Returns the number of rules removed.
    """
    paths = collect_paths(meta, cfg)
    tools = cfg.permissions.investigation_tools
    if not tools or not paths:
        return 0

    to_remove: set[str] = {_bash_entry(tool, path) for path in paths for tool in tools}

    project_dirs = project_dirs_from_meta(meta)
    project_dir = project_dirs[0] if project_dirs else None
    data = _load_settings(project_dir)
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        return 0
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        return 0

    new_allow = [r for r in allow if r not in to_remove]
    removed = len(allow) - len(new_allow)

    if removed:
        perms["allow"] = new_allow
        data["permissions"] = perms
        _save_settings(data, project_dir)

    return removed


# ── Setup (one-shot atomic write) ─────────────────────────────────────────────


def _apply_path_rules(
    meta: ProjectMeta,
    cfg: ProjConfig,
    allow_set: set[str],
    new_entries: list[str],
    *,
    sandbox_mode: bool = False,
    data: dict[str, object] | None = None,
) -> int:
    """Add Read+Edit rules for writable repo paths and Read-only for reference repos and tracking dir.

    In sandbox mode, writable paths are also added to sandbox.filesystem.allowWrite.
    Returns count added.
    """
    count = 0
    for repo in meta.repos:
        abs_path = str(Path(repo.path).expanduser().resolve())
        prefix = f"//{abs_path.strip('/')}"
        entries = [f"Read({prefix}/**)"]
        if not repo.reference:
            entries.append(f"Edit({prefix}/**)")
            # In sandbox mode, also add to sandbox.filesystem.allowWrite
            if sandbox_mode and data is not None:
                if _add_sandbox_write_path(data, abs_path):
                    count += 1
        for entry in entries:
            if entry not in allow_set:
                new_entries.append(entry)
                allow_set.add(entry)
                count += 1
    if cfg.tracking_dir:
        abs_path = str(Path(cfg.tracking_dir).expanduser().resolve())
        if sandbox_mode and data is not None:
            if _add_sandbox_write_path(data, abs_path):
                count += 1
        for entry in _path_allow_entries(abs_path):
            if entry not in allow_set:
                new_entries.append(entry)
                allow_set.add(entry)
                count += 1
    return count


def _apply_bash_rules(
    meta: ProjectMeta,
    cfg: ProjConfig,
    allow_set: set[str],
    new_entries: list[str],
) -> int:
    """Add scoped Bash investigation-tool rules. Returns count added."""
    if not cfg.permissions.investigation_tools:
        return 0
    count = 0
    for path in collect_paths(meta, cfg):
        for tool in cfg.permissions.investigation_tools:
            entry = _bash_entry(tool, path)
            if entry not in allow_set:
                new_entries.append(entry)
                allow_set.add(entry)
                count += 1
    return count


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


def setup_permissions(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    grant_path_access: bool = True,
    grant_investigation_tools_flag: bool = True,
    mcp_servers: list[str] | None = None,
) -> dict[str, int]:
    """Add all project permission rules in a single atomic write.

    Targets settings.json or settings.local.json depending on sandbox mode.

    Consolidates what would otherwise be 5-7 sequential tool calls:
    - Read+Edit rules for each repo path and the tracking dir
    - Bash investigation-tool rules (scoped to project paths)
    - MCP server wildcard rules
    - (sandbox mode) sandbox.filesystem.allowWrite paths

    Returns a dict with counts: {"path_rules": N, "bash_rules": N, "mcp_rules": N}.
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
    counts = {"path_rules": 0, "bash_rules": 0, "mcp_rules": 0}

    if grant_path_access:
        counts["path_rules"] = _apply_path_rules(
            meta, cfg, allow_set, new_entries,
            sandbox_mode=sandbox_mode, data=data,
        )

    if grant_investigation_tools_flag:
        counts["bash_rules"] = _apply_bash_rules(meta, cfg, allow_set, new_entries)

    if mcp_servers:
        counts["mcp_rules"] = _apply_mcp_rules(mcp_servers, allow_set, new_entries)

    # Add Bash(zoxide *) rule when zoxide integration is enabled
    from server.lib.zoxide import resolve_enabled as _zoxide_enabled
    if _zoxide_enabled(cfg, meta):
        zoxide_entry = "Bash(zoxide *)"
        if zoxide_entry not in allow_set:
            new_entries.append(zoxide_entry)
            allow_set.add(zoxide_entry)
            counts["bash_rules"] += 1

    if new_entries or sum(counts.values()) > 0:
        allow.extend(new_entries)
        perms["allow"] = allow
        data["permissions"] = perms
        _save_settings(data, project_dir)

    return counts


# ── MCP tool registration ──────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register proj_grant_tool_permissions, proj_setup_permissions, and proj_revoke_tool_permissions tools with the MCP app."""

    @app.tool(
        description=(
            "Grant Bash allow rules for read-only investigation tools (grep, find, ls, etc.) "
            "for a project's directories and worktree paths. "
            "Rules are scoped to the project paths. Idempotent — safe to call multiple times. "
            "Automatically detects sandbox mode and writes to settings.local.json if enabled."
        )
    )
    def proj_grant_tool_permissions(project_name: str | None = None) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        if name not in index.projects:
            return f"Project '{name}' not found."
        meta = storage.load_meta(cfg, name)
        added = grant_investigation_tools(meta, cfg)
        paths = collect_paths(meta, cfg)
        tools = cfg.permissions.investigation_tools
        if added == 0:
            return (
                f"✅ Investigation tool permissions already up to date for '{name}' "
                f"({len(tools)} tools, {len(paths)} path(s))."
            )
        return (
            f"✅ Added {added} Bash allow rule(s) for '{name}' "
            f"({len(tools)} tools × {len(paths)} path(s))."
        )

    @app.tool(
        description=(
            "Grant all permission rules for a project in one atomic write. "
            "Replaces calling perms_add_allow + proj_grant_tool_permissions + perms_add_mcp_allow "
            "separately. Idempotent. "
            "Automatically detects sandbox mode and writes to settings.local.json if enabled. "
            "In sandbox mode, writable paths are also added to sandbox.filesystem.allowWrite. "
            "grant_path_access=true adds Read+Edit rules for repo paths and tracking dir. "
            "grant_investigation_tools=true adds scoped Bash rules (grep, find, ls, etc.). "
            "mcp_servers is a list of server names to add wildcard allow rules for "
            "(e.g. ['plugin_proj_proj', 'plugin_perms_perms', 'trello'])."
        )
    )
    def proj_setup_permissions(
        project_name: str | None = None,
        grant_path_access: bool = True,
        grant_investigation_tools: bool = True,
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
        counts = setup_permissions(
            meta,
            cfg,
            grant_path_access=grant_path_access,
            grant_investigation_tools_flag=grant_investigation_tools,
            mcp_servers=mcp_servers or [],
        )
        total = sum(counts.values())
        if total == 0:
            return f"✅ All permission rules already up to date for '{name}'."
        parts = []
        if counts["path_rules"]:
            parts.append(f"{counts['path_rules']} path rule(s)")
        if counts["bash_rules"]:
            parts.append(f"{counts['bash_rules']} Bash rule(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        return f"✅ Added {total} rule(s) for '{name}': {', '.join(parts)}."

    @app.tool(
        description=(
            "Remove Bash allow rules for investigation tools for a project's directories. "
            "Only removes rules that were added by proj_grant_tool_permissions — "
            "other allow rules are never touched. Idempotent. "
            "Automatically detects sandbox mode."
        )
    )
    def proj_revoke_tool_permissions(project_name: str | None = None) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        if name not in index.projects:
            return f"Project '{name}' not found."
        meta = storage.load_meta(cfg, name)
        removed = revoke_investigation_tools(meta, cfg)
        if removed == 0:
            return f"✅ No investigation tool rules found for '{name}' — nothing to remove."
        return f"✅ Removed {removed} Bash allow rule(s) for '{name}'."
