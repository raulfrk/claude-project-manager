"""Config tools — init wizard and config load/update."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.enums import Priority
from server.lib.models import ProjConfig

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

CONFIG_NOT_FOUND_MSG = (
    "proj plugin not configured. "
    "Please run /proj:init-plugin to set up the plugin before using any other commands."
)


class ConfigError(Exception):
    """Raised when config is missing or invalid."""


def require_config() -> ProjConfig:
    """Load config or raise ConfigError if it doesn't exist."""
    if not storage.config_exists():
        raise ConfigError(CONFIG_NOT_FOUND_MSG)
    return storage.load_config()


def require_project(project_name: str | None) -> tuple[ProjConfig, str] | str:
    """Load config and resolve active project in one call.

    Returns (cfg, name) on success, or an error string on failure.
    Tools should do::

        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result
    """
    from server.lib import state  # lazy to avoid module-level cycle

    cfg = require_config()
    name = state.resolve_project(project_name)
    if not name:
        return "No active project."
    return cfg, name


def register(app: FastMCP) -> None:
    """Register config_load, config_init, and config_update tools with the MCP app."""

    @app.tool(
        description="Check if proj plugin is configured. Returns config summary or setup instructions."  # noqa: E501
    )
    def config_load() -> str:
        if not storage.config_exists():
            return CONFIG_NOT_FOUND_MSG
        cfg = storage.load_config()
        return (
            f"proj plugin configured:\n"
            f"  tracking_dir: {cfg.tracking_dir}\n"
            f"  projects_base_dir: {cfg.projects_base_dir or '(not set)'}\n"
            f"  git_integration: {cfg.git_integration}\n"
            f"  default_priority: {cfg.default_priority}\n"
            f"  permissions.auto_grant: {cfg.permissions.auto_grant}\n"
            f"  permissions.auto_allow_mcps: {cfg.permissions.auto_allow_mcps}\n"
            f"  todoist.enabled: {cfg.todoist.enabled}\n"
            f"  todoist.auto_sync: {cfg.todoist.auto_sync}\n"
            f"  todoist.mcp_server: {cfg.todoist.mcp_server}\n"
            f"  todoist.root_only: {cfg.todoist.root_only}\n"
            f"  trello.enabled: {cfg.trello.enabled}\n"
            f"  trello.mcp_server: {cfg.trello.mcp_server}\n"
            f"  trello.default_board_id: {cfg.trello.default_board_id or '(not set)'}\n"
            f"  trello.on_delete: {cfg.trello.on_delete}\n"
            f"  perms_integration: {cfg.perms_integration}\n"
            f"  worktree_integration: {cfg.worktree_integration}\n"
            f"  zoxide_integration: {cfg.zoxide_integration}\n"
            f"  claudemd_management: {cfg.claudemd_management}\n"
            f"  archive.destination: {cfg.archive.destination}\n"
            f"  git_tracking.enabled: {cfg.git_tracking.enabled}\n"
            f"  git_tracking.github_enabled: {cfg.git_tracking.github_enabled}\n"
            f"  git_tracking.github_repo_format: {cfg.git_tracking.github_repo_format}\n"
            f"  config_path: {storage.config_path()}"
        )

    @app.tool(
        description="Initialize proj plugin configuration. Called by /proj:init-plugin skill."
    )
    def config_init(
        tracking_dir: str = "~/projects/tracking",
        projects_base_dir: str | None = None,
        auto_grant_permissions: bool = True,
        auto_allow_mcps: bool = True,
        todoist_enabled: bool = False,
        todoist_auto_sync: bool = True,
        todoist_mcp_server: str = "claude_ai_Todoist",
        todoist_root_only: bool = False,
        trello_enabled: bool = False,
        trello_mcp_server: str = "trello",
        trello_default_board_id: str = "",
        trello_on_delete: str = "archive",
        git_integration: bool = True,
        default_priority: str = "medium",
        perms_integration: bool = False,
        worktree_integration: bool = False,
        zoxide_integration: bool = False,
        claudemd_management: bool = False,
        git_tracking_enabled: bool = False,
        git_tracking_github_enabled: bool = False,
        git_tracking_github_repo_format: str = "tracking",
        archive_destination: str = "~/projects/archived",
    ) -> str:
        cfg = ProjConfig(
            tracking_dir=tracking_dir,
            projects_base_dir=projects_base_dir,
            git_integration=git_integration,
            default_priority=default_priority,
            perms_integration=perms_integration,
            worktree_integration=worktree_integration,
            zoxide_integration=zoxide_integration,
            claudemd_management=claudemd_management,
        )
        cfg.permissions.auto_grant = auto_grant_permissions
        cfg.permissions.auto_allow_mcps = auto_allow_mcps
        cfg.todoist.enabled = todoist_enabled
        cfg.todoist.auto_sync = todoist_auto_sync
        cfg.todoist.mcp_server = todoist_mcp_server
        cfg.todoist.root_only = todoist_root_only
        cfg.trello.enabled = trello_enabled
        cfg.trello.mcp_server = trello_mcp_server
        cfg.trello.default_board_id = trello_default_board_id
        cfg.trello.on_delete = trello_on_delete
        cfg.git_tracking.enabled = git_tracking_enabled
        cfg.git_tracking.github_enabled = git_tracking_github_enabled
        cfg.git_tracking.github_repo_format = git_tracking_github_repo_format
        cfg.archive.destination = archive_destination
        storage.save_config(cfg)

        # Set file permissions to 600
        storage.config_path().chmod(0o600)

        return f"Configuration saved to {storage.config_path()}."

    def _check_integration_plugin(flag: bool, prefixes: list[str], plugin_label: str) -> str | None:
        """Return a warning string if flag=True but no matching MCP rule is in settings.json.

        Checks that at least one entry in permissions.allow starts with one of the given
        prefixes (or exactly equals the wildcard literal). Returns None when flag is False
        or the plugin is found. Never raises — a missing or unreadable settings.json is
        treated the same as plugin absent.
        """
        if not flag:
            return None
        from server.tools.perms_grant import _load_settings  # lazy import to avoid circular dep

        data = _load_settings()
        perms = data.get("permissions", {})
        allow_list: list[object] = []
        if isinstance(perms, dict):
            raw = perms.get("allow", [])
            if isinstance(raw, list):
                allow_list = raw
        found = any(
            isinstance(r, str) and any(r.startswith(p) or r == p + "*" for p in prefixes)
            for r in allow_list
        )
        if not found:
            return (
                f"Warning: {plugin_label} MCP server not found in settings.json. "
                f"Install it and re-run /proj:init-plugin."
            )
        return None

    @app.tool(description="Update individual proj config settings.")
    def config_update(
        tracking_dir: str | None = None,
        projects_base_dir: str | None = None,
        auto_grant_permissions: bool | None = None,
        auto_allow_mcps: bool | None = None,
        todoist_enabled: bool | None = None,
        todoist_mcp_server: str | None = None,
        todoist_root_only: bool | None = None,
        trello_enabled: bool | None = None,
        trello_mcp_server: str | None = None,
        trello_default_board_id: str | None = None,
        trello_on_delete: str | None = None,
        git_integration: bool | None = None,
        default_priority: str | None = None,
        perms_integration: bool | None = None,
        worktree_integration: bool | None = None,
        zoxide_integration: bool | None = None,
        claudemd_management: bool | None = None,
        git_tracking_enabled: bool | None = None,
        git_tracking_github_enabled: bool | None = None,
        git_tracking_github_repo_format: str | None = None,
        investigation_tools: list[str] | None = None,
        archive_destination: str | None = None,
    ) -> str:
        if default_priority is not None and default_priority not in (
            Priority.LOW, Priority.MEDIUM, Priority.HIGH
        ):
            return (
                f"Invalid default_priority '{default_priority}'. "
                f"Must be one of: {', '.join(sorted(p.value for p in Priority))}."
            )

        for field_name, path_value in (
            ("tracking_dir", tracking_dir),
            ("projects_base_dir", projects_base_dir),
        ):
            if path_value is not None:
                if not path_value or "\x00" in path_value:
                    return (
                        f"Invalid {field_name}: must be a non-empty string without null bytes."
                    )

        if investigation_tools is not None:
            if not isinstance(investigation_tools, list) or not all(
                isinstance(t, str) for t in investigation_tools
            ):
                return "Invalid investigation_tools: must be a list of strings."

        if todoist_mcp_server is not None:
            if not todoist_mcp_server or "\x00" in todoist_mcp_server:
                return (
                    "Invalid todoist_mcp_server: must be a non-empty string without null bytes."
                )

        if trello_mcp_server is not None:
            if not trello_mcp_server or "\x00" in trello_mcp_server:
                return (
                    "Invalid trello_mcp_server: must be a non-empty string without null bytes."
                )

        if trello_on_delete is not None and trello_on_delete not in ("archive", "delete"):
            return "Invalid trello_on_delete: must be 'archive' or 'delete'."

        if git_tracking_github_repo_format is not None:
            if not git_tracking_github_repo_format or "\x00" in git_tracking_github_repo_format:
                return "Invalid git_tracking_github_repo_format: must be a non-empty string without null bytes."

        if archive_destination is not None:
            if not archive_destination or "\x00" in archive_destination:
                return "Invalid archive_destination: must be a non-empty string without null bytes."

        cfg = require_config()
        if tracking_dir is not None:
            cfg.tracking_dir = tracking_dir
        if projects_base_dir is not None:
            cfg.projects_base_dir = projects_base_dir
        if auto_grant_permissions is not None:
            cfg.permissions.auto_grant = auto_grant_permissions
        if auto_allow_mcps is not None:
            cfg.permissions.auto_allow_mcps = auto_allow_mcps
        if todoist_enabled is not None:
            cfg.todoist.enabled = todoist_enabled
        if todoist_mcp_server is not None:
            cfg.todoist.mcp_server = todoist_mcp_server
        if todoist_root_only is not None:
            cfg.todoist.root_only = todoist_root_only
        if trello_enabled is not None:
            cfg.trello.enabled = trello_enabled
        if trello_mcp_server is not None:
            cfg.trello.mcp_server = trello_mcp_server
        if trello_default_board_id is not None:
            cfg.trello.default_board_id = trello_default_board_id
        if trello_on_delete is not None:
            cfg.trello.on_delete = trello_on_delete
        if git_integration is not None:
            cfg.git_integration = git_integration
        if default_priority is not None:
            cfg.default_priority = default_priority
        if perms_integration is not None:
            cfg.perms_integration = perms_integration
        if worktree_integration is not None:
            cfg.worktree_integration = worktree_integration
        if zoxide_integration is not None:
            cfg.zoxide_integration = zoxide_integration
        if claudemd_management is not None:
            cfg.claudemd_management = claudemd_management
        if git_tracking_enabled is not None:
            cfg.git_tracking.enabled = git_tracking_enabled
        if git_tracking_github_enabled is not None:
            cfg.git_tracking.github_enabled = git_tracking_github_enabled
        if git_tracking_github_repo_format is not None:
            cfg.git_tracking.github_repo_format = git_tracking_github_repo_format
        if investigation_tools is not None:
            cfg.permissions.investigation_tools = investigation_tools
        if archive_destination is not None:
            cfg.archive.destination = archive_destination
        storage.save_config(cfg)
        warnings: list[str] = []
        if perms_integration is True:
            w = _check_integration_plugin(
                True,
                ["mcp__plugin_perms_perms__", "mcp__perms__"],
                "perms plugin",
            )
            if w:
                warnings.append(w)
        if worktree_integration is True:
            w = _check_integration_plugin(
                True,
                ["mcp__plugin_worktree_worktree__", "mcp__worktree__"],
                "worktree plugin",
            )
            if w:
                warnings.append(w)
        if warnings:
            return "Configuration updated.\n" + "\n".join(warnings)
        return "Configuration updated."
