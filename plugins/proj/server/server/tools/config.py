"""Config tools — init wizard and config load/update."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.enums import Priority
from server.lib.models import (
    _REMOVED_QUALITY_LEVELS,
    ContextInjectionConfig,
    ContextInjectionSectionsConfig,
    ProjConfig,
    QualityLevel,
)

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
        description=(
            "Check if proj plugin is configured. Returns config summary or setup instructions."
        )
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
            f"  trello.list_mappings.projects: {cfg.trello.list_mappings.projects}\n"
            f"  trello.list_mappings.tasks: {cfg.trello.list_mappings.tasks}\n"
            f"  trello.list_mappings.active: {cfg.trello.list_mappings.active or '(not set)'}\n"
            f"  trello.list_mappings.pending: {cfg.trello.list_mappings.pending or '(not set)'}\n"
            f"  trello.list_mappings.archived: {cfg.trello.list_mappings.archived or '(not set)'}\n"
            f"  jira.enabled: {cfg.jira.enabled}\n"
            f"  jira.default_user: {cfg.jira.default_user or '(not set)'}\n"
            f"  sandbox_integration: {cfg.sandbox_integration}\n"
            f"  worktree_integration: {cfg.worktree_integration}\n"
            f"  zoxide_integration: {cfg.zoxide_integration}\n"
            f"  claudemd_management: {cfg.claudemd_management}\n"
            f"  archive.destination: {cfg.archive.destination}\n"
            f"  archive.purge_after_days: {cfg.archive.purge_after_days or '(not set)'}\n"
            f"  archive.trash_grace_days: {cfg.archive.trash_grace_days}\n"
            f"  git_tracking.enabled: {cfg.git_tracking.enabled}\n"
            f"  git_tracking.github_enabled: {cfg.git_tracking.github_enabled}\n"
            f"  git_tracking.github_repo_format: {cfg.git_tracking.github_repo_format}\n"
            f"  smart_gate: {cfg.smart_gate}\n"
            f"  quality_level: {cfg.quality_level}\n"
            f"  worktree_isolation: {cfg.worktree_isolation}\n"
            f"  context_injection:\n"
            f"    enabled: {cfg.context_injection.enabled}\n"
            f"    budget: {cfg.context_injection.budget}\n"
            f"    recency_window: {cfg.context_injection.recency_window}h\n"
            f"    sections.notes: {cfg.context_injection.sections.notes}%\n"
            f"    sections.decisions: {cfg.context_injection.sections.decisions}%\n"
            f"    sections.knowledge: {cfg.context_injection.sections.knowledge}%\n"
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
        trello_list_projects: str = "Projects",
        trello_list_tasks: str = "proj-tasks",
        trello_list_active: str = "",
        trello_list_pending: str = "",
        trello_list_archived: str = "",
        jira_enabled: bool = False,
        jira_default_user: str = "",
        git_integration: bool = True,
        default_priority: str = "medium",
        sandbox_integration: bool = False,
        worktree_integration: bool = False,
        zoxide_integration: bool = False,
        claudemd_management: bool = False,
        git_tracking_enabled: bool = False,
        git_tracking_github_enabled: bool = False,
        git_tracking_github_repo_format: str = "tracking",
        archive_destination: str = "~/projects/archived",
        archive_purge_after_days: int | None = None,
        archive_trash_grace_days: int = 7,
        quality_level: str = "careful",
        smart_gate: bool = True,
        worktree_isolation: bool = False,
        context_injection_enabled: bool = True,
        context_injection_budget: int = 2000,
        context_injection_recency_window: int = 24,
        context_injection_notes_pct: int = 40,
        context_injection_decisions_pct: int = 35,
        context_injection_knowledge_pct: int = 25,
        permissions_projects_root: str | None = None,
        permissions_tracking_root: str | None = None,
    ) -> str:
        cfg = ProjConfig(
            tracking_dir=tracking_dir,
            projects_base_dir=projects_base_dir,
            git_integration=git_integration,
            default_priority=default_priority,
            sandbox_integration=sandbox_integration,
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
        cfg.trello.list_mappings.projects = trello_list_projects
        cfg.trello.list_mappings.tasks = trello_list_tasks
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
        if quality_level in _REMOVED_QUALITY_LEVELS:
            return _REMOVED_QUALITY_LEVELS[quality_level]
        _valid_quality = tuple(q.value for q in QualityLevel)
        if quality_level not in _valid_quality:
            return (
                f"Invalid quality_level '{quality_level}'. "
                f"Must be one of: {', '.join(_valid_quality)}."
            )
        cfg.quality_level = quality_level
        cfg.smart_gate = smart_gate
        cfg.worktree_isolation = worktree_isolation
        cfg.context_injection = ContextInjectionConfig(
            enabled=context_injection_enabled,
            budget=context_injection_budget,
            recency_window=context_injection_recency_window,
            sections=ContextInjectionSectionsConfig(
                notes=context_injection_notes_pct,
                decisions=context_injection_decisions_pct,
                knowledge=context_injection_knowledge_pct,
            ),
        )
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
        trello_list_projects: str | None = None,
        trello_list_tasks: str | None = None,
        trello_list_active: str | None = None,
        trello_list_pending: str | None = None,
        trello_list_archived: str | None = None,
        jira_enabled: bool | None = None,
        jira_default_user: str | None = None,
        git_integration: bool | None = None,
        default_priority: str | None = None,
        sandbox_integration: bool | None = None,
        worktree_integration: bool | None = None,
        zoxide_integration: bool | None = None,
        claudemd_management: bool | None = None,
        git_tracking_enabled: bool | None = None,
        git_tracking_github_enabled: bool | None = None,
        git_tracking_github_repo_format: str | None = None,
        archive_destination: str | None = None,
        archive_purge_after_days: int | None = None,
        archive_trash_grace_days: int | None = None,
        quality_level: str | None = None,
        smart_gate: bool | None = None,
        worktree_isolation: bool | None = None,
        context_injection_enabled: bool | None = None,
        context_injection_budget: int | None = None,
        context_injection_recency_window: int | None = None,
        context_injection_notes_pct: int | None = None,
        context_injection_decisions_pct: int | None = None,
        context_injection_knowledge_pct: int | None = None,
        permissions_projects_root: str | None = None,
        permissions_tracking_root: str | None = None,
    ) -> str:
        if default_priority is not None and default_priority not in (
            Priority.LOW,
            Priority.MEDIUM,
            Priority.HIGH,
        ):
            return (
                f"Invalid default_priority '{default_priority}'. "
                f"Must be one of: {', '.join(sorted(p.value for p in Priority))}."
            )

        for field_name, path_value in (
            ("tracking_dir", tracking_dir),
            ("projects_base_dir", projects_base_dir),
        ):
            if path_value is not None and (not path_value or "\x00" in path_value):
                return f"Invalid {field_name}: must be a non-empty string without null bytes."

        if todoist_mcp_server is not None and (
            not todoist_mcp_server or "\x00" in todoist_mcp_server
        ):
            return "Invalid todoist_mcp_server: must be a non-empty string without null bytes."

        if trello_on_delete is not None and trello_on_delete not in (
            "archive",
            "delete",
        ):
            return "Invalid trello_on_delete: must be 'archive' or 'delete'."

        if git_tracking_github_repo_format is not None and (
            not git_tracking_github_repo_format or "\x00" in git_tracking_github_repo_format
        ):
            return (
                "Invalid git_tracking_github_repo_format:"
                " must be a non-empty string without null bytes."
            )

        if archive_destination is not None and (
            not archive_destination or "\x00" in archive_destination
        ):
            return "Invalid archive_destination: must be a non-empty string without null bytes."

        if archive_purge_after_days is not None and (
            not isinstance(archive_purge_after_days, int) or archive_purge_after_days <= 0
        ):
            return "Invalid archive_purge_after_days: must be a positive integer."

        if archive_trash_grace_days is not None and (
            not isinstance(archive_trash_grace_days, int) or archive_trash_grace_days <= 0
        ):
            return "Invalid archive_trash_grace_days: must be a positive integer."

        if quality_level is not None and quality_level in _REMOVED_QUALITY_LEVELS:
            return _REMOVED_QUALITY_LEVELS[quality_level]
        _valid_quality = tuple(q.value for q in QualityLevel)
        if quality_level is not None and quality_level not in _valid_quality:
            return (
                f"Invalid quality_level '{quality_level}'. "
                f"Must be one of: {', '.join(_valid_quality)}."
            )

        if context_injection_budget is not None and (
            not isinstance(context_injection_budget, int) or context_injection_budget <= 0
        ):
            return "Invalid context_injection_budget: must be a positive integer."

        if context_injection_recency_window is not None and (
            not isinstance(context_injection_recency_window, int)
            or context_injection_recency_window <= 0
        ):
            return "Invalid context_injection_recency_window: must be a positive integer."

        for _pct_name, _pct_val in (
            ("context_injection_notes_pct", context_injection_notes_pct),
            (
                "context_injection_decisions_pct",
                context_injection_decisions_pct,
            ),
            (
                "context_injection_knowledge_pct",
                context_injection_knowledge_pct,
            ),
        ):
            if _pct_val is not None and (
                not isinstance(_pct_val, int) or _pct_val < 0 or _pct_val > 100
            ):
                return f"Invalid {_pct_name}: must be an integer between 0 and 100."

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
        if trello_list_projects is not None:
            cfg.trello.list_mappings.projects = trello_list_projects
        if trello_list_tasks is not None:
            cfg.trello.list_mappings.tasks = trello_list_tasks
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
        if sandbox_integration is not None:
            cfg.sandbox_integration = sandbox_integration
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
        if quality_level is not None:
            cfg.quality_level = quality_level
        if smart_gate is not None:
            cfg.smart_gate = smart_gate
        if worktree_isolation is not None:
            cfg.worktree_isolation = worktree_isolation
        if context_injection_enabled is not None:
            cfg.context_injection.enabled = context_injection_enabled
        if context_injection_budget is not None:
            cfg.context_injection.budget = context_injection_budget
        if context_injection_recency_window is not None:
            cfg.context_injection.recency_window = context_injection_recency_window
        if context_injection_notes_pct is not None:
            cfg.context_injection.sections.notes = context_injection_notes_pct
        if context_injection_decisions_pct is not None:
            cfg.context_injection.sections.decisions = context_injection_decisions_pct
        if context_injection_knowledge_pct is not None:
            cfg.context_injection.sections.knowledge = context_injection_knowledge_pct
        storage.save_config(cfg)
        return "Configuration updated."
