"""Shared derivation logic for sandbox paths, MCP rules, and skill prefixes.

Used by both perms_sync and perms_grant to avoid duplicating derivation logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.lib.models import ProjConfig, ProjectMeta


def derive_write_paths(
    meta: ProjectMeta,
    cfg: ProjConfig,
    worktree_root_dir: str | None = None,
) -> set[str]:
    """Derive the resolved absolute paths expected in sandbox allowWrite / additionalDirectories.

    Unifies the logic previously split across ``_derive_expected_sandbox_paths``,
    ``_derive_expected_additional_dirs`` (perms_sync), and
    ``_collect_sandbox_write_paths`` (perms_grant).  All paths have trailing
    slashes stripped.
    """
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

    if cfg.worktree_integration and worktree_root_dir:
        wt_root = str(Path(worktree_root_dir).expanduser().resolve()).rstrip("/")
        if not any(wt_root.startswith(p + "/") or wt_root == p for p in paths):
            paths.add(wt_root)

    return paths


def derive_mcp_rules(meta: ProjectMeta, cfg: ProjConfig) -> set[str]:
    """Derive expected MCP wildcard rules for permissions.allow.

    Only MCP wildcard rules are expected -- Read/Edit/Bash rules are no
    longer managed in permissions.allow (sandbox allowWrite handles file access).
    """
    rules: set[str] = set()

    if cfg.permissions.auto_allow_mcps:
        # proj is always present -- it's the running plugin itself
        rules.add("mcp__plugin_proj_proj__*")
        # sandbox and worktree are only expected when their integrations are enabled
        if cfg.sandbox_integration:
            rules.add("mcp__plugin_sandbox_sandbox__*")
        if cfg.worktree_integration:
            rules.add("mcp__plugin_worktree_worktree__*")
        if cfg.todoist.enabled:
            rules.add("mcp__todoist__*")  # Fixed prefix -- local plugin
        if cfg.jira.enabled:
            rules.add("mcp__plugin_jira_jira__*")
        if cfg.trello.enabled:
            rules.add("mcp__plugin_trello_trello__*")

    # Global Claude.ai MCP servers -- always expected, unconditionally
    rules.add("mcp__claude_ai_Excalidraw__*")
    rules.add("mcp__claude_ai_Mermaid_Chart__*")
    return rules


def derive_skill_prefixes(cfg: ProjConfig) -> set[str]:
    """Derive expected Skill() allow prefixes from config."""
    prefixes: set[str] = {"Skill(proj:*)"}
    if cfg.worktree_integration:
        prefixes.add("Skill(worktree:*)")
    # hooks and review are always expected when proj plugin is active
    prefixes.add("Skill(hooks:*)")
    prefixes.add("Skill(review:*)")
    return prefixes
