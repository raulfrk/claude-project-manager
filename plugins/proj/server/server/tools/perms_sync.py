"""Sandbox sync tool — compare expected vs actual allow rules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools._perms_common import derive_mcp_rules, derive_skill_prefixes, derive_write_paths
from server.tools.config import require_config

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.fastmcp import FastMCP

    from server.lib.models import ProjConfig, ProjectMeta


def _extract_mcp_servers(missing_mcp: list[str]) -> list[str]:
    """Extract server names from MCP wildcard rules like ``mcp__server__*``."""
    servers: list[str] = []
    for rule in missing_mcp:
        # Strip leading "mcp__" and trailing "__*"
        if rule.startswith("mcp__") and rule.endswith("__*"):
            server = rule[len("mcp__") : -len("__*")]
            servers.append(server)
    return servers


def _extract_skill_prefixes(missing_skills: list[str]) -> list[str]:
    """Extract prefixes from Skill() rules like ``Skill(proj:*)``."""
    prefixes: list[str] = []
    for rule in missing_skills:
        if rule.startswith("Skill(") and rule.endswith("*)"):
            # "Skill(proj:*)" → "proj:"
            prefix = rule[len("Skill(") : -len("*)")]
            prefixes.append(prefix)
    return prefixes


def run_sync(
    meta: ProjectMeta,
    cfg: ProjConfig,
    *,
    actual_rules: set[str],
    actual_sandbox_paths: set[str],
    actual_additional_dirs: set[str] | None = None,
    actual_skill_allow: set[str] | None = None,
    actual_deny_rules: list[str] | None = None,
    sandbox_mode: bool,
    apply: bool = False,
    worktree_root_dir: str | None = None,
    batch_setup_fn: Callable[..., str] | None = None,
) -> str:
    expected = derive_mcp_rules(meta, cfg)
    missing = expected - actual_rules

    # In sandbox mode, also check sandbox.filesystem.allowWrite
    missing_sandbox_paths: set[str] = set()
    if sandbox_mode:
        expected_paths = derive_write_paths(meta, cfg, worktree_root_dir=worktree_root_dir)
        missing_sandbox_paths = expected_paths - actual_sandbox_paths

    # Check skill allow rules
    missing_skills: set[str] = set()
    expected_skills = derive_skill_prefixes(cfg)
    if actual_skill_allow is not None:
        missing_skills = expected_skills - actual_skill_allow

    # Check permissions.additionalDirectories
    missing_additional_dirs: set[str] = set()
    expected_additional = derive_write_paths(meta, cfg, worktree_root_dir=worktree_root_dir)
    if actual_additional_dirs is not None:
        missing_additional_dirs = expected_additional - actual_additional_dirs

    target_name = "settings.json"

    # Check deny rules presence (v4 mode = projects_root is set)
    deny_warning = ""
    if cfg.permissions.projects_root and not actual_deny_rules:
        deny_warning = (
            "\n⚠️ No deny rules found. Run `/proj:migrate-sandbox` to install default deny rules."
        )

    if (
        not missing
        and not missing_sandbox_paths
        and not missing_additional_dirs
        and not missing_skills
    ):
        msg = f"✅ {target_name} is in sync — all expected rules are present."
        if deny_warning:
            msg += deny_warning
        return msg

    # Group by type (only MCP rules expected in permissions.allow now)
    missing_mcp = sorted(r for r in missing if r.startswith("mcp__"))
    missing_skill_list = sorted(missing_skills)

    if apply:
        from server.tools.perms_grant import setup_permissions

        mcp_servers = _extract_mcp_servers(missing_mcp)
        skill_prefixes = _extract_skill_prefixes(missing_skill_list)
        counts = setup_permissions(
            meta,
            cfg,
            mcp_servers=mcp_servers,
            skill_prefixes=skill_prefixes or None,
            worktree_root_dir=worktree_root_dir,
            batch_setup_fn=batch_setup_fn,
        )
        total = sum(counts.values())
        if total == 0 and not missing_sandbox_paths and not missing_additional_dirs:
            msg = f"✅ {target_name} is in sync — all expected rules are present."
            if deny_warning:
                msg += deny_warning
            return msg
        parts: list[str] = []
        if counts["sandbox_paths"]:
            parts.append(f"{counts['sandbox_paths']} sandbox path(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        if counts.get("skill_rules"):
            parts.append(f"{counts['skill_rules']} skill rule(s)")
        if counts.get("additional_directories"):
            parts.append(f"{counts['additional_directories']} additional dir(s)")
        applied_total = total
        msg = f"✅ Applied missing rules — added {applied_total} rule(s): {', '.join(parts)}."
        if deny_warning:
            msg += deny_warning
        return msg

    lines = [f"❌ Missing rules in {target_name}:\n"]
    if missing_mcp:
        lines.append("**MCP rules:**")
        lines.extend(f"  - `{r}`" for r in missing_mcp)
    if missing_skill_list:
        lines.append("\n**Skill rules:**")
        lines.extend(f"  - `{r}`" for r in missing_skill_list)
    if missing_sandbox_paths:
        lines.append("\n**Sandbox allowWrite paths:**")
        lines.extend(f"  - `{p}`" for p in sorted(missing_sandbox_paths))
    if missing_additional_dirs:
        lines.append("\n**Additional directories:**")
        lines.extend(f"  - `{p}`" for p in sorted(missing_additional_dirs))
    hint = "\nRun `proj_setup_permissions` to add all missing rules at once."
    if missing_mcp:
        hint += "\nOr use `sandbox_add_mcp_allow` to add MCP rules individually."
    if missing_skill_list:
        hint += "\nOr use `sandbox_add_skill_allow` to add skill rules individually."
    lines.append(hint)
    if deny_warning:
        lines.append(deny_warning)
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
        actual_skill_allow: list[str] | None = None,
        actual_deny_rules: list[str] | None = None,
        sandbox_mode: bool = False,
        worktree_root_dir: str | None = None,
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
            actual_additional_dirs=set(actual_additional_dirs)
            if actual_additional_dirs is not None
            else None,
            actual_skill_allow=set(actual_skill_allow) if actual_skill_allow is not None else None,
            actual_deny_rules=actual_deny_rules,
            sandbox_mode=sandbox_mode,
            apply=apply,
            worktree_root_dir=worktree_root_dir,
        )
