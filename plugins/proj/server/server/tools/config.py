"""Config tools — init wizard and config load/update."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.enums import Priority
from server.lib.models import ProjConfig, QualityLevel, ResilienceConfig, SmartGateConfig, TeamModeConfig

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
            f"  permissions.projects_root: {cfg.permissions.projects_root or '(not set)'}\n"
            f"  permissions.tracking_root: {cfg.permissions.tracking_root or '(not set)'}\n"
            f"  todoist.enabled: {cfg.todoist.enabled}\n"
            f"  todoist.auto_sync: {cfg.todoist.auto_sync}\n"
            f"  todoist.mcp_server: {cfg.todoist.mcp_server}\n"
            f"  todoist.root_only: {cfg.todoist.root_only}\n"
            f"  trello.enabled: {cfg.trello.enabled}\n"
            f"  trello.auto_sync: {cfg.trello.auto_sync}\n"
            f"  trello.default_board_id: {cfg.trello.default_board_id or '(not set)'}\n"
            f"  trello.on_delete: {cfg.trello.on_delete}\n"
            f"  trello.list_mappings.active: {cfg.trello.list_mappings.active or '(not set)'}\n"
            f"  trello.list_mappings.pending: {cfg.trello.list_mappings.pending or '(not set)'}\n"
            f"  trello.list_mappings.archived: {cfg.trello.list_mappings.archived or '(not set)'}\n"
            f"  jira.enabled: {cfg.jira.enabled}\n"
            f"  jira.default_user: {cfg.jira.default_user or '(not set)'}\n"
            f"  perms_integration: {cfg.perms_integration}\n"
            f"  worktree_integration: {cfg.worktree_integration}\n"
            f"  zoxide_integration: {cfg.zoxide_integration}\n"
            f"  claudemd_management: {cfg.claudemd_management}\n"
            f"  archive.destination: {cfg.archive.destination}\n"
            f"  archive.purge_after_days: {cfg.archive.purge_after_days or '(not set)'}\n"
            f"  archive.trash_grace_days: {cfg.archive.trash_grace_days}\n"
            f"  git_tracking.enabled: {cfg.git_tracking.enabled}\n"
            f"  git_tracking.github_enabled: {cfg.git_tracking.github_enabled}\n"
            f"  git_tracking.github_repo_format: {cfg.git_tracking.github_repo_format}\n"
            f"  team_mode.enabled: {cfg.team_mode.enabled}\n"
            f"  team_mode.max_agents: {cfg.team_mode.max_agents}\n"
            f"  team_mode.trust_level: {cfg.team_mode.trust_level}\n"
            f"  resilience.failure_threshold: {cfg.resilience.failure_threshold}\n"
            f"  resilience.recovery_timeout: {cfg.resilience.recovery_timeout}\n"
            f"  smart_gate:\n"
            f"    enabled: {cfg.smart_gate.enabled}\n"
            f"    auto_execute_threshold: {cfg.smart_gate.auto_execute_threshold}\n"
            f"    light_review_threshold: {cfg.smart_gate.light_review_threshold}\n"
            f"    critical_path_patterns: {cfg.smart_gate.critical_path_patterns}\n"
            f"  quality_level: {cfg.quality_level}\n"
            f"  worktree_isolation: {cfg.worktree_isolation}\n"
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
        trello_auto_sync: bool = True,
        trello_default_board_id: str = "",
        trello_on_delete: str = "archive",
        trello_list_active: str = "",
        trello_list_pending: str = "",
        trello_list_archived: str = "",
        jira_enabled: bool = False,
        jira_default_user: str = "",
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
        archive_purge_after_days: int | None = None,
        archive_trash_grace_days: int = 7,
        team_mode_enabled: bool = False,
        team_mode_max_agents: int = 4,
        team_mode_trust_level: int = 1,
        resilience_failure_threshold: int = 3,
        resilience_recovery_timeout: int = 300,
        quality_level: str = "balanced",
        smart_gate_enabled: bool = True,
        worktree_isolation: bool = False,
        permissions_projects_root: str | None = None,
        permissions_tracking_root: str | None = None,
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
        if permissions_projects_root is not None:
            cfg.permissions.projects_root = permissions_projects_root
        elif projects_base_dir:
            cfg.permissions.projects_root = projects_base_dir
        if permissions_tracking_root is not None:
            cfg.permissions.tracking_root = permissions_tracking_root
        elif tracking_dir:
            cfg.permissions.tracking_root = tracking_dir
        cfg.todoist.enabled = todoist_enabled
        cfg.todoist.auto_sync = todoist_auto_sync
        cfg.todoist.mcp_server = todoist_mcp_server
        cfg.todoist.root_only = todoist_root_only
        cfg.trello.enabled = trello_enabled
        cfg.trello.auto_sync = trello_auto_sync
        cfg.trello.default_board_id = trello_default_board_id
        cfg.trello.on_delete = trello_on_delete
        cfg.trello.list_mappings.active = trello_list_active
        cfg.trello.list_mappings.pending = trello_list_pending
        cfg.trello.list_mappings.archived = trello_list_archived
        cfg.jira.enabled = jira_enabled
        cfg.jira.default_user = jira_default_user
        cfg.git_tracking.enabled = git_tracking_enabled
        cfg.git_tracking.github_enabled = git_tracking_github_enabled
        cfg.git_tracking.github_repo_format = git_tracking_github_repo_format
        cfg.archive.destination = archive_destination
        cfg.archive.purge_after_days = archive_purge_after_days
        cfg.archive.trash_grace_days = archive_trash_grace_days
        cfg.team_mode = TeamModeConfig(
            enabled=team_mode_enabled,
            max_agents=team_mode_max_agents,
            trust_level=team_mode_trust_level,
        )
        cfg.resilience = ResilienceConfig(
            failure_threshold=resilience_failure_threshold,
            recovery_timeout=resilience_recovery_timeout,
        )
        _valid_quality = tuple(q.value for q in QualityLevel)
        if quality_level not in _valid_quality:
            return (
                f"Invalid quality_level '{quality_level}'. "
                f"Must be one of: {', '.join(_valid_quality)}."
            )
        cfg.quality_level = quality_level
        cfg.smart_gate = SmartGateConfig(enabled=smart_gate_enabled)
        cfg.worktree_isolation = worktree_isolation
        storage.save_config(cfg)

        # Set file permissions to 600
        storage.config_path().chmod(0o600)

        return f"Configuration saved to {storage.config_path()}."

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
        trello_auto_sync: bool | None = None,
        trello_default_board_id: str | None = None,
        trello_on_delete: str | None = None,
        trello_list_active: str | None = None,
        trello_list_pending: str | None = None,
        trello_list_archived: str | None = None,
        jira_enabled: bool | None = None,
        jira_default_user: str | None = None,
        git_integration: bool | None = None,
        default_priority: str | None = None,
        perms_integration: bool | None = None,
        worktree_integration: bool | None = None,
        zoxide_integration: bool | None = None,
        claudemd_management: bool | None = None,
        git_tracking_enabled: bool | None = None,
        git_tracking_github_enabled: bool | None = None,
        git_tracking_github_repo_format: str | None = None,
        archive_destination: str | None = None,
        archive_purge_after_days: int | None = None,
        archive_trash_grace_days: int | None = None,
        team_mode_enabled: bool | None = None,
        team_mode_max_agents: int | None = None,
        team_mode_trust_level: int | None = None,
        resilience_failure_threshold: int | None = None,
        resilience_recovery_timeout: int | None = None,
        quality_level: str | None = None,
        smart_gate_enabled: bool | None = None,
        smart_gate_auto_execute_threshold: int | None = None,
        smart_gate_light_review_threshold: int | None = None,
        smart_gate_critical_path_patterns: list[str] | None = None,
        worktree_isolation: bool | None = None,
        permissions_projects_root: str | None = None,
        permissions_tracking_root: str | None = None,
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

        if todoist_mcp_server is not None:
            if not todoist_mcp_server or "\x00" in todoist_mcp_server:
                return (
                    "Invalid todoist_mcp_server: must be a non-empty string without null bytes."
                )

        if trello_on_delete is not None and trello_on_delete not in ("archive", "delete"):
            return "Invalid trello_on_delete: must be 'archive' or 'delete'."

        if git_tracking_github_repo_format is not None:
            if not git_tracking_github_repo_format or "\x00" in git_tracking_github_repo_format:
                return "Invalid git_tracking_github_repo_format: must be a non-empty string without null bytes."

        if archive_destination is not None:
            if not archive_destination or "\x00" in archive_destination:
                return "Invalid archive_destination: must be a non-empty string without null bytes."

        if archive_purge_after_days is not None:
            if not isinstance(archive_purge_after_days, int) or archive_purge_after_days <= 0:
                return "Invalid archive_purge_after_days: must be a positive integer."

        if archive_trash_grace_days is not None:
            if not isinstance(archive_trash_grace_days, int) or archive_trash_grace_days <= 0:
                return "Invalid archive_trash_grace_days: must be a positive integer."

        if team_mode_max_agents is not None:
            if not isinstance(team_mode_max_agents, int) or team_mode_max_agents <= 0:
                return "Invalid team_mode_max_agents: must be a positive integer."

        if team_mode_trust_level is not None:
            if not isinstance(team_mode_trust_level, int) or team_mode_trust_level not in (0, 1, 2, 3):
                return "Invalid team_mode_trust_level: must be 0, 1, 2, or 3."

        if resilience_failure_threshold is not None:
            if not isinstance(resilience_failure_threshold, int) or resilience_failure_threshold <= 0:
                return "Invalid resilience_failure_threshold: must be a positive integer."

        if resilience_recovery_timeout is not None:
            if not isinstance(resilience_recovery_timeout, int) or resilience_recovery_timeout <= 0:
                return "Invalid resilience_recovery_timeout: must be a positive integer."

        _valid_quality = tuple(q.value for q in QualityLevel)
        if quality_level is not None and quality_level not in _valid_quality:
            return (
                f"Invalid quality_level '{quality_level}'. "
                f"Must be one of: {', '.join(_valid_quality)}."
            )

        if smart_gate_auto_execute_threshold is not None:
            if not isinstance(smart_gate_auto_execute_threshold, int) or smart_gate_auto_execute_threshold < 0:
                return "Invalid smart_gate_auto_execute_threshold: must be a non-negative integer."

        if smart_gate_light_review_threshold is not None:
            if not isinstance(smart_gate_light_review_threshold, int) or smart_gate_light_review_threshold < 0:
                return "Invalid smart_gate_light_review_threshold: must be a non-negative integer."

        cfg = require_config()
        if tracking_dir is not None:
            cfg.tracking_dir = tracking_dir
        if projects_base_dir is not None:
            cfg.projects_base_dir = projects_base_dir
        if auto_grant_permissions is not None:
            cfg.permissions.auto_grant = auto_grant_permissions
        if auto_allow_mcps is not None:
            cfg.permissions.auto_allow_mcps = auto_allow_mcps
        if permissions_projects_root is not None:
            cfg.permissions.projects_root = permissions_projects_root
        if permissions_tracking_root is not None:
            cfg.permissions.tracking_root = permissions_tracking_root
        if todoist_enabled is not None:
            cfg.todoist.enabled = todoist_enabled
        if todoist_mcp_server is not None:
            cfg.todoist.mcp_server = todoist_mcp_server
        if todoist_root_only is not None:
            cfg.todoist.root_only = todoist_root_only
        if trello_enabled is not None:
            cfg.trello.enabled = trello_enabled
        if trello_auto_sync is not None:
            cfg.trello.auto_sync = trello_auto_sync
        if trello_default_board_id is not None:
            cfg.trello.default_board_id = trello_default_board_id
        if trello_on_delete is not None:
            cfg.trello.on_delete = trello_on_delete
        if trello_list_active is not None:
            cfg.trello.list_mappings.active = trello_list_active
        if trello_list_pending is not None:
            cfg.trello.list_mappings.pending = trello_list_pending
        if trello_list_archived is not None:
            cfg.trello.list_mappings.archived = trello_list_archived
        if jira_enabled is not None:
            cfg.jira.enabled = jira_enabled
        if jira_default_user is not None:
            cfg.jira.default_user = jira_default_user
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
        if archive_destination is not None:
            cfg.archive.destination = archive_destination
        if archive_purge_after_days is not None:
            cfg.archive.purge_after_days = archive_purge_after_days
        if archive_trash_grace_days is not None:
            cfg.archive.trash_grace_days = archive_trash_grace_days
        if team_mode_enabled is not None:
            cfg.team_mode.enabled = team_mode_enabled
        if team_mode_max_agents is not None:
            cfg.team_mode.max_agents = team_mode_max_agents
        if team_mode_trust_level is not None:
            cfg.team_mode.trust_level = team_mode_trust_level
        if resilience_failure_threshold is not None:
            cfg.resilience.failure_threshold = resilience_failure_threshold
        if resilience_recovery_timeout is not None:
            cfg.resilience.recovery_timeout = resilience_recovery_timeout
        if quality_level is not None:
            cfg.quality_level = quality_level
        if smart_gate_enabled is not None:
            cfg.smart_gate.enabled = smart_gate_enabled
        if smart_gate_auto_execute_threshold is not None:
            cfg.smart_gate.auto_execute_threshold = smart_gate_auto_execute_threshold
        if smart_gate_light_review_threshold is not None:
            cfg.smart_gate.light_review_threshold = smart_gate_light_review_threshold
        if smart_gate_critical_path_patterns is not None:
            cfg.smart_gate.critical_path_patterns = smart_gate_critical_path_patterns
        if worktree_isolation is not None:
            cfg.worktree_isolation = worktree_isolation
        storage.save_config(cfg)
        return "Configuration updated."
