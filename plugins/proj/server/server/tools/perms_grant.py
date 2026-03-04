"""Grant / revoke Bash investigation-tool permissions for project paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectMeta
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
_WORKTREE_CONFIG = Path.home() / ".claude" / "worktree.yaml"


# ── Settings I/O ──────────────────────────────────────────────────────────────


def _load_settings() -> dict[str, object]:
    if not _USER_SETTINGS.exists():
        return {}
    return json.loads(_USER_SETTINGS.read_text())  # type: ignore[return-value]  # json.loads returns Any; caller expects dict


def _save_settings(data: dict[str, object]) -> None:
    storage.atomic_write_json(_USER_SETTINGS, data)


# ── Path helpers ───────────────────────────────────────────────────────────────


def _bash_entry(tool: str, abs_path: str) -> str:
    """Build a scoped Bash allow rule: ``Bash(grep //home/user/proj/**)``.

    The double-slash prefix is required by Claude Code for absolute paths.
    """
    prefix = f"//{abs_path.strip('/')}"
    return f"Bash({tool} {prefix}/**)"


def collect_paths(meta: ProjectMeta, cfg: ProjConfig) -> list[str]:
    """Collect all paths that should receive investigation-tool access.

    Includes all registered project repo paths plus, when worktree_integration
    is enabled, any base-repo paths from ``~/.claude/worktree.yaml`` that are
    not already covered.
    """
    paths: list[str] = [repo.path for repo in meta.repos]

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

    data = _load_settings()
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
        _save_settings(data)

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

    data = _load_settings()
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
        _save_settings(data)

    return removed


# ── Setup (one-shot atomic write) ─────────────────────────────────────────────


def _apply_path_rules(
    meta: ProjectMeta,
    cfg: ProjConfig,
    allow_set: set[str],
    new_entries: list[str],
) -> int:
    """Add Read+Edit rules for writable repo paths and Read-only for reference repos and tracking dir. Returns count added."""
    count = 0
    for repo in meta.repos:
        abs_path = str(Path(repo.path).expanduser().resolve())
        prefix = f"//{abs_path.strip('/')}"
        entries = [f"Read({prefix}/**)"]
        if not repo.reference:
            entries.append(f"Edit({prefix}/**)")
        for entry in entries:
            if entry not in allow_set:
                new_entries.append(entry)
                allow_set.add(entry)
                count += 1
    if cfg.tracking_dir:
        abs_path = str(Path(cfg.tracking_dir).expanduser().resolve())
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
    """Add all project permission rules in a single atomic settings.json write.

    Consolidates what would otherwise be 5-7 sequential tool calls:
    - Read+Edit rules for each repo path and the tracking dir
    - Bash investigation-tool rules (scoped to project paths)
    - MCP server wildcard rules

    Returns a dict with counts: {"path_rules": N, "bash_rules": N, "mcp_rules": N}.
    All zero means the file was not written (all rules already present).
    Idempotent.
    """
    data = _load_settings()
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
        counts["path_rules"] = _apply_path_rules(meta, cfg, allow_set, new_entries)

    if grant_investigation_tools_flag:
        counts["bash_rules"] = _apply_bash_rules(meta, cfg, allow_set, new_entries)

    if mcp_servers:
        counts["mcp_rules"] = _apply_mcp_rules(mcp_servers, allow_set, new_entries)

    if new_entries:
        allow.extend(new_entries)
        perms["allow"] = allow
        data["permissions"] = perms
        _save_settings(data)

    return counts


# ── MCP tool registration ──────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register proj_grant_tool_permissions, proj_setup_permissions, and proj_revoke_tool_permissions tools with the MCP app."""

    @app.tool(
        description=(
            "Grant Bash allow rules for read-only investigation tools (grep, find, ls, etc.) "
            "for a project's directories and worktree paths. "
            "Rules are scoped to the project paths. Idempotent — safe to call multiple times."
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
            "Grant all permission rules for a project in one atomic settings.json write. "
            "Replaces calling perms_add_allow + proj_grant_tool_permissions + perms_add_mcp_allow "
            "separately. Idempotent. "
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
            "other allow rules are never touched. Idempotent."
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
