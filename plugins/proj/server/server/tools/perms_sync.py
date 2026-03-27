"""Perms sync tool — compare expected vs actual allow rules."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectMeta
from server.lib.perms_helpers import project_dirs_from_meta
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _derive_expected_rules(meta: ProjectMeta, cfg: ProjConfig) -> set[str]:
    """Derive expected permissions.allow rules.

    Only MCP wildcard rules are expected now — Read/Edit/Bash rules are no
    longer managed in permissions.allow (sandbox allowWrite handles file access).
    """
    rules: set[str] = set()

    if cfg.permissions.auto_allow_mcps:
        # proj is always present — it's the running plugin itself
        rules.add("mcp__plugin_proj_proj__*")
        # perms and worktree are only expected when their integrations are enabled
        if cfg.perms_integration:
            rules.add("mcp__plugin_perms_perms__*")
        if cfg.worktree_integration:
            rules.add("mcp__plugin_worktree_worktree__*")
        if cfg.todoist.enabled:
            rules.add("mcp__todoist__*")  # Fixed prefix — local plugin
        if cfg.jira.enabled:
            rules.add("mcp__plugin_jira_jira__*")
        if cfg.trello.enabled:
            rules.add("mcp__plugin_trello_trello__*")
    # Global Claude.ai MCP servers — always expected, unconditionally
    rules.add("mcp__claude_ai_Excalidraw__*")
    rules.add("mcp__claude_ai_Mermaid_Chart__*")
    return rules


def _derive_expected_sandbox_paths(meta: ProjectMeta, cfg: ProjConfig) -> set[str]:
    """Derive the paths expected in sandbox.filesystem.allowWrite."""
    paths: set[str] = set()
    for repo in meta.repos:
        if not repo.reference:
            paths.add(repo.path.rstrip("/"))
    if cfg.tracking_dir:
        paths.add(str(Path(cfg.tracking_dir).expanduser().resolve()).rstrip("/"))
    return paths


def _derive_expected_additional_dirs(meta: ProjectMeta, cfg: ProjConfig) -> set[str]:
    """Derive the paths expected in permissions.additionalDirectories."""
    paths: set[str] = set()
    for repo in meta.repos:
        if not repo.reference:
            paths.add(str(Path(repo.path).expanduser().resolve()).rstrip("/"))
    if cfg.tracking_dir:
        paths.add(str(Path(cfg.tracking_dir).expanduser().resolve()).rstrip("/"))
    return paths


def _extract_mcp_servers(missing_mcp: list[str]) -> list[str]:
    """Extract server names from MCP wildcard rules like ``mcp__server__*``."""
    servers: list[str] = []
    for rule in missing_mcp:
        # Strip leading "mcp__" and trailing "__*"
        if rule.startswith("mcp__") and rule.endswith("__*"):
            server = rule[len("mcp__") : -len("__*")]
            servers.append(server)
    return servers


def run_sync(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    actual_rules: set[str],
    actual_sandbox_paths: set[str],
    actual_additional_dirs: set[str] | None = None,
    sandbox_mode: bool,
    apply: bool = False,
    batch_setup_fn: Callable[..., str] | None = None,
) -> str:
    expected = _derive_expected_rules(meta, cfg)
    missing = expected - actual_rules

    # In sandbox mode, also check sandbox.filesystem.allowWrite
    missing_sandbox_paths: set[str] = set()
    if sandbox_mode:
        expected_paths = _derive_expected_sandbox_paths(meta, cfg)
        missing_sandbox_paths = expected_paths - actual_sandbox_paths

    # Check permissions.additionalDirectories
    missing_additional_dirs: set[str] = set()
    expected_additional = _derive_expected_additional_dirs(meta, cfg)
    if actual_additional_dirs is not None:
        missing_additional_dirs = expected_additional - actual_additional_dirs

    target_name = "settings.local.json" if sandbox_mode else "settings.json"

    if not missing and not missing_sandbox_paths and not missing_additional_dirs:
        return f"✅ {target_name} is in sync — all expected rules are present."

    # Group by type (only MCP rules expected in permissions.allow now)
    missing_mcp = sorted(r for r in missing if r.startswith("mcp__"))

    if apply:
        from server.tools.perms_grant import setup_permissions

        mcp_servers = _extract_mcp_servers(missing_mcp)
        counts = setup_permissions(
            meta,
            cfg,
            mcp_servers=mcp_servers,
            batch_setup_fn=batch_setup_fn,
        )
        total = sum(counts.values())
        if total == 0 and not missing_sandbox_paths and not missing_additional_dirs:
            return f"✅ {target_name} is in sync — all expected rules are present."
        parts: list[str] = []
        if counts["sandbox_paths"]:
            parts.append(f"{counts['sandbox_paths']} sandbox path(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        if counts.get("additional_directories"):
            parts.append(f"{counts['additional_directories']} additional dir(s)")
        applied_total = total
        return f"✅ Applied missing rules — added {applied_total} rule(s): {', '.join(parts)}."

    lines = [f"❌ Missing rules in {target_name}:\n"]
    if missing_mcp:
        lines.append("**MCP rules:**")
        lines.extend(f"  - `{r}`" for r in missing_mcp)
    if missing_sandbox_paths:
        lines.append("\n**Sandbox allowWrite paths:**")
        lines.extend(f"  - `{p}`" for p in sorted(missing_sandbox_paths))
    if missing_additional_dirs:
        lines.append("\n**Additional directories:**")
        lines.extend(f"  - `{p}`" for p in sorted(missing_additional_dirs))
    hint = "\nRun `proj_setup_permissions` to add all missing rules at once."
    if missing_mcp:
        hint += (
            "\nOr use `perms_add_mcp_allow` / `perms_batch_add_mcp_allow` "
            "to add MCP rules individually."
        )
    lines.append(hint)
    return "\n".join(lines)


def register(app: FastMCP) -> None:
    """Register the proj_perms_sync tool with the MCP app."""

    @app.tool(
        description=(
            "Check if settings allow rules match the active project config. "
            "Reports missing rules (one-way check — extras in actual are fine). "
            "Does not auto-fix. Idempotent. "
            "Caller must pass actual_rules, actual_sandbox_paths, and sandbox_mode "
            "(obtained from perms MCP tools). "
            "In sandbox mode, also checks sandbox.filesystem.allowWrite paths. "
            "Pass apply=true to automatically add all missing rules in one atomic write."
        )
    )
    def proj_perms_sync(
        project_name: str | None = None,
        apply: bool = False,
        actual_rules: list[str] | None = None,
        actual_sandbox_paths: list[str] | None = None,
        actual_additional_dirs: list[str] | None = None,
        sandbox_mode: bool = False,
    ) -> str:
        if actual_rules is None:
            return "Error: actual_rules is a required parameter."
        cfg = require_config()
        index = storage.load_index(cfg)
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        if name not in index.projects:
            return f"Project '{name}' not found."
        meta = storage.load_meta(cfg, name)
        return run_sync(
            meta,
            cfg,
            actual_rules=set(actual_rules),
            actual_sandbox_paths=set(actual_sandbox_paths or []),
            actual_additional_dirs=set(actual_additional_dirs) if actual_additional_dirs is not None else None,
            sandbox_mode=sandbox_mode,
            apply=apply,
        )
