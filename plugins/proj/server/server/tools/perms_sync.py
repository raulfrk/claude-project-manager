"""Perms sync tool — compare expected vs actual allow rules (settings.json or settings.local.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectMeta
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _local_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.local.json"


def _is_sandbox_enabled(project_dir: Path | None = None) -> bool:
    """Check if sandbox mode is enabled in user-level or project-level settings.local.json."""
    paths = [_local_settings_path()]
    if project_dir:
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


def _derive_expected_rules(meta: ProjectMeta, cfg: ProjConfig) -> set[str]:
    from server.tools.perms_grant import collect_paths

    rules: set[str] = set()
    for repo in meta.repos:
        # Double-slash prefix required by Claude Code for absolute paths
        prefix = f"//{repo.path.strip('/')}"
        rules.add(f"Read({prefix}/**)")
        if not repo.reference:
            rules.add(f"Edit({prefix}/**)")

    # Bash rules for read-only investigation tools
    if cfg.permissions.investigation_tools:
        for path in collect_paths(meta, cfg):
            prefix = f"//{path.strip('/')}"
            for tool in cfg.permissions.investigation_tools:
                rules.add(f"Bash({tool} {prefix}/**)")

    if cfg.permissions.auto_allow_mcps:
        # proj is always present — it's the running plugin itself
        rules.add("mcp__proj__*")
        # perms and worktree are only expected when their integrations are enabled
        if cfg.perms_integration:
            rules.add("mcp__perms__*")
        if cfg.worktree_integration:
            rules.add("mcp__worktree__*")
        if cfg.todoist.enabled:
            rules.add(f"mcp__{cfg.todoist.mcp_server}__*")
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


def _load_actual_rules(project_dir: Path | None = None) -> set[str]:
    """Load permissions.allow rules from the effective settings file."""
    sandbox_mode = _is_sandbox_enabled(project_dir)
    path = _local_settings_path() if sandbox_mode else _settings_path()
    if not path.exists():
        return set()
    data: dict[str, object] = json.loads(path.read_text())
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        return set()
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        return set()
    return set(str(r) for r in allow)


def _load_actual_sandbox_paths() -> set[str]:
    """Load sandbox.filesystem.allowWrite paths from settings.local.json."""
    path = _local_settings_path()
    if not path.exists():
        return set()
    data: dict[str, object] = json.loads(path.read_text())
    sandbox = data.get("sandbox", {})
    if not isinstance(sandbox, dict):
        return set()
    fs = sandbox.get("filesystem", {})
    if not isinstance(fs, dict):
        return set()
    aw = fs.get("allowWrite", [])
    if not isinstance(aw, list):
        return set()
    return set(str(p) for p in aw)


def _extract_mcp_servers(missing_mcp: list[str]) -> list[str]:
    """Extract server names from MCP wildcard rules like ``mcp__server__*``."""
    servers: list[str] = []
    for rule in missing_mcp:
        # Strip leading "mcp__" and trailing "__*"
        if rule.startswith("mcp__") and rule.endswith("__*"):
            server = rule[len("mcp__") : -len("__*")]
            servers.append(server)
    return servers


def _project_dir_from_meta(meta: ProjectMeta) -> Path | None:
    """Derive the project directory from the first non-reference repo path."""
    for repo in meta.repos:
        if not repo.reference:
            return Path(repo.path)
    if meta.repos:
        return Path(meta.repos[0].path)
    return None


def run_sync(meta: ProjectMeta, cfg: ProjConfig, *, apply: bool = False) -> str:
    project_dir = _project_dir_from_meta(meta)
    sandbox_mode = _is_sandbox_enabled(project_dir)
    expected = _derive_expected_rules(meta, cfg)
    actual = _load_actual_rules(project_dir)
    missing = expected - actual

    # In sandbox mode, also check sandbox.filesystem.allowWrite
    missing_sandbox_paths: set[str] = set()
    if sandbox_mode:
        expected_paths = _derive_expected_sandbox_paths(meta, cfg)
        actual_paths = _load_actual_sandbox_paths()
        missing_sandbox_paths = expected_paths - actual_paths

    target_name = "settings.local.json" if sandbox_mode else "settings.json"

    if not missing and not missing_sandbox_paths:
        return f"✅ {target_name} is in sync — all expected rules are present."

    # Group by type
    missing_path = sorted(
        r for r in missing if r.startswith("Read(") or r.startswith("Edit(")
    )
    missing_mcp = sorted(r for r in missing if r.startswith("mcp__"))
    missing_bash = sorted(r for r in missing if r.startswith("Bash("))

    if apply:
        from server.tools.perms_grant import setup_permissions

        mcp_servers = _extract_mcp_servers(missing_mcp)
        counts = setup_permissions(
            meta,
            cfg,
            grant_path_access=True,
            grant_investigation_tools_flag=True,
            mcp_servers=mcp_servers,
        )
        total = sum(counts.values())
        if total == 0 and not missing_sandbox_paths:
            return f"✅ {target_name} is in sync — all expected rules are present."
        parts: list[str] = []
        if counts["path_rules"]:
            parts.append(f"{counts['path_rules']} path rule(s)")
        if counts["bash_rules"]:
            parts.append(f"{counts['bash_rules']} Bash rule(s)")
        if counts["mcp_rules"]:
            parts.append(f"{counts['mcp_rules']} MCP rule(s)")
        applied_total = total
        return f"✅ Applied missing rules — added {applied_total} rule(s): {', '.join(parts)}."

    lines = [f"❌ Missing rules in {target_name}:\n"]
    if missing_path:
        lines.append("**Directory rules:**")
        lines.extend(f"  - `{r}`" for r in missing_path)
    if missing_bash:
        lines.append("\n**Bash tool rules:**")
        lines.extend(f"  - `{r}`" for r in missing_bash)
    if missing_mcp:
        lines.append("\n**MCP rules:**")
        lines.extend(f"  - `{r}`" for r in missing_mcp)
    if missing_sandbox_paths:
        lines.append("\n**Sandbox allowWrite paths:**")
        lines.extend(f"  - `{p}`" for p in sorted(missing_sandbox_paths))
    lines.append(
        "\nRun `proj_setup_permissions` to add all missing rules at once, "
        "or `proj_grant_tool_permissions` (Bash rules), "
        "`perms_add_allow` (directory rules), "
        "or `perms_add_mcp_allow` / `perms_batch_add_mcp_allow` (MCP rules) individually."
    )
    return "\n".join(lines)


def register(app: FastMCP) -> None:
    """Register the proj_perms_sync tool with the MCP app."""

    @app.tool(
        description=(
            "Check if settings allow rules match the active project config. "
            "Reports missing rules (one-way check — extras in actual are fine). "
            "Does not auto-fix. Idempotent. "
            "Automatically detects sandbox mode and checks settings.local.json if enabled. "
            "In sandbox mode, also checks sandbox.filesystem.allowWrite paths. "
            "Pass apply=true to automatically add all missing rules in one atomic write."
        )
    )
    def proj_perms_sync(project_name: str | None = None, apply: bool = False) -> str:
        cfg = require_config()
        index = storage.load_index(cfg)
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        if name not in index.projects:
            return f"Project '{name}' not found."
        meta = storage.load_meta(cfg, name)
        return run_sync(meta, cfg, apply=apply)
