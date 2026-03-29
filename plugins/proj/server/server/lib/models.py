"""Data models for proj plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QualityLevel(str, Enum):
    """Quality level presets for run/execute workflows."""
    FAST = "fast"
    BALANCED = "balanced"
    CAREFUL = "careful"
    PARANOID = "paranoid"


@dataclass
class SmartGateConfig:
    """Configuration for smart gate complexity scoring."""
    enabled: bool = True
    auto_execute_threshold: int = 3   # score 0-3 → AUTO-EXECUTE
    light_review_threshold: int = 7   # score 4-7 → LIGHT REVIEW
    # score 8-14 → FULL REVIEW (implicit)
    critical_path_patterns: list[str] = field(default_factory=lambda: [
        "*.env*", "*secret*", "*credential*", "*key*", "*auth*", "*permission*",
        "Dockerfile", "docker-compose*", ".github/workflows/*",
        "pyproject.toml", "package.json", "settings.json", "proj.yaml", "*.config.*",
    ])

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "auto_execute_threshold": self.auto_execute_threshold,
            "light_review_threshold": self.light_review_threshold,
            "critical_path_patterns": self.critical_path_patterns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SmartGateConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            auto_execute_threshold=int(data.get("auto_execute_threshold", 3)),
            light_review_threshold=int(data.get("light_review_threshold", 7)),
            critical_path_patterns=list(data.get("critical_path_patterns", cls().critical_path_patterns)),
        )


# ── Config ────────────────────────────────────────────────────────────────────


@dataclass
class TodoistSync:
    enabled: bool = False
    auto_sync: bool = True
    mcp_server: str = "claude_ai_Todoist"  # Deprecated: ignored, local plugin uses fixed "todoist" prefix
    root_only: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "auto_sync": self.auto_sync,
            "mcp_server": self.mcp_server,
            "root_only": self.root_only,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TodoistSync:
        return cls(
            enabled=bool(data.get("enabled", False)),
            auto_sync=bool(data.get("auto_sync", True)),
            mcp_server=str(data.get("mcp_server", "claude_ai_Todoist")),
            root_only=bool(data.get("root_only", False)),
        )


@dataclass
class GitTracking:
    enabled: bool = False
    github_enabled: bool = False
    github_repo_format: str = "tracking"

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "github_enabled": self.github_enabled,
            "github_repo_format": self.github_repo_format,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> GitTracking:
        return cls(
            enabled=bool(data.get("enabled", False)),
            github_enabled=bool(data.get("github_enabled", False)),
            github_repo_format=str(data.get("github_repo_format", "tracking")),
        )


@dataclass
class ArchiveConfig:
    destination: str = "~/projects/archived"
    purge_after_days: int | None = None
    trash_grace_days: int = 7
    backup_retention_days: int = 30

    def to_dict(self) -> dict[str, object]:
        return {
            "destination": self.destination,
            "purge_after_days": self.purge_after_days,
            "trash_grace_days": self.trash_grace_days,
            "backup_retention_days": self.backup_retention_days,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ArchiveConfig:
        raw = data.get("purge_after_days")
        tgd_raw = data.get("trash_grace_days")
        brd_raw = data.get("backup_retention_days")
        return cls(
            destination=str(data.get("destination", "~/projects/archived")),
            purge_after_days=int(raw) if raw is not None else None,
            trash_grace_days=int(tgd_raw) if tgd_raw is not None else 7,
            backup_retention_days=int(brd_raw) if brd_raw is not None else 30,
        )


@dataclass
class TrelloListMappings:
    created: str = "Backlog"  # List name or ID where new todos are added as cards
    done: str = "Done"        # List name or ID where completed todos are moved
    # Project-status-based list mappings (map project status to Trello list name)
    active: str = ""          # List name for active projects (empty = not configured)
    pending: str = ""         # List name for paused/blocked projects (empty = not configured)
    archived: str = ""        # List name for archived projects (empty = not configured)

    def to_dict(self) -> dict[str, object]:
        return {
            "created": self.created,
            "done": self.done,
            "active": self.active,
            "pending": self.pending,
            "archived": self.archived,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TrelloListMappings:
        return cls(
            created=str(data.get("created", "Backlog")),
            done=str(data.get("done", "Done")),
            active=str(data.get("active", "")),
            pending=str(data.get("pending", "")),
            archived=str(data.get("archived", "")),
        )


@dataclass
class TrelloSync:
    """Global Trello sync configuration stored under sync.trello in proj.yaml."""

    enabled: bool = False
    auto_sync: bool = True
    default_board_id: str = ""
    default_list: str = "Active"
    list_mappings: TrelloListMappings = field(default_factory=TrelloListMappings)
    on_delete: str = "archive"  # "archive" or "delete"

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "auto_sync": self.auto_sync,
            "default_board_id": self.default_board_id,
            "default_list": self.default_list,
            "list_mappings": self.list_mappings.to_dict(),
            "on_delete": self.on_delete,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TrelloSync:
        lm_raw = data.get("list_mappings", {})
        return cls(
            enabled=bool(data.get("enabled", False)),
            auto_sync=bool(data.get("auto_sync", True)),
            default_board_id=str(data.get("default_board_id", "")),
            default_list=str(data.get("default_list", "Active")),
            list_mappings=TrelloListMappings.from_dict(lm_raw if isinstance(lm_raw, dict) else {}),  # type: ignore[arg-type]
            on_delete=str(data.get("on_delete", "archive")),
        )


@dataclass
class JiraSync:
    """Global Jira sync configuration stored under sync.jira in proj.yaml."""

    enabled: bool = False
    default_user: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "default_user": self.default_user,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> JiraSync:
        return cls(
            enabled=bool(data.get("enabled", False)),
            default_user=str(data.get("default_user", "")),
        )


@dataclass
class PermissionsConfig:
    auto_grant: bool = True
    auto_allow_mcps: bool = True  # add mcp__<server>__* allow rules at init time
    projects_root: str | None = None
    tracking_root: str | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "auto_grant": self.auto_grant,
            "auto_allow_mcps": self.auto_allow_mcps,
        }
        if self.projects_root is not None:
            d["projects_root"] = self.projects_root
        if self.tracking_root is not None:
            d["tracking_root"] = self.tracking_root
        return d

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PermissionsConfig:
        # Note: "investigation_tools" was removed in v0.37 (sandbox-primary).
        # Old YAML files may still contain it; it is silently ignored here.
        return cls(
            auto_grant=bool(data.get("auto_grant", True)),
            auto_allow_mcps=bool(data.get("auto_allow_mcps", True)),
            projects_root=data.get("projects_root") or None,
            tracking_root=data.get("tracking_root") or None,
        )


@dataclass
class TeamModeConfig:
    enabled: bool = False
    max_agents: int = 4
    trust_level: int = 1  # 0=supervised, 1=guided, 2=autonomous, 3=full-auto

    def to_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled, "max_agents": self.max_agents, "trust_level": self.trust_level}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TeamModeConfig:
        return cls(
            enabled=bool(data.get("enabled", False)),
            max_agents=int(data.get("max_agents", 4)),
            trust_level=int(data.get("trust_level", 1)),
        )


@dataclass
class ResilienceConfig:
    failure_threshold: int = 3
    recovery_timeout: int = 300

    def to_dict(self) -> dict[str, object]:
        return {
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ResilienceConfig:
        return cls(
            failure_threshold=int(data.get("failure_threshold", 3)),
            recovery_timeout=int(data.get("recovery_timeout", 300)),
        )


@dataclass
class ProjConfig:
    tracking_dir: str = "~/projects/tracking"
    projects_base_dir: str | None = None
    git_integration: bool = True
    default_priority: str = "medium"
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    todoist: TodoistSync = field(default_factory=TodoistSync)
    trello: TrelloSync = field(default_factory=TrelloSync)
    jira: JiraSync = field(default_factory=JiraSync)
    git_tracking: GitTracking = field(default_factory=GitTracking)
    # Optional integration flags set by /proj:init-plugin
    perms_integration: bool = False
    worktree_integration: bool = False
    zoxide_integration: bool = False
    claudemd_management: bool = False
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)
    team_mode: TeamModeConfig = field(default_factory=TeamModeConfig)
    resilience: ResilienceConfig = field(default_factory=ResilienceConfig)
    smart_gate: SmartGateConfig = field(default_factory=SmartGateConfig)
    quality_level: str = "balanced"
    worktree_isolation: bool = False  # opt-in: isolate parallel agents in git worktrees

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "tracking_dir": self.tracking_dir,
            "projects_base_dir": self.projects_base_dir,
            "git_integration": self.git_integration,
            "default_priority": self.default_priority,
            "permissions": self.permissions.to_dict(),
            "sync": {"todoist": self.todoist.to_dict(), "trello": self.trello.to_dict(), "jira": self.jira.to_dict()},
            "git_tracking": self.git_tracking.to_dict(),
            "perms_integration": self.perms_integration,
            "worktree_integration": self.worktree_integration,
            "zoxide_integration": self.zoxide_integration,
            "claudemd_management": self.claudemd_management,
            "archive": self.archive.to_dict(),
            "team_mode": self.team_mode.to_dict(),
            "resilience": self.resilience.to_dict(),
            "smart_gate": self.smart_gate.to_dict(),
            "quality_level": self.quality_level,
            "worktree_isolation": self.worktree_isolation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjConfig:
        sync = data.get("sync", {})
        if not isinstance(sync, dict):
            sync = {}
        todoist_raw = sync.get("todoist", {})
        if not isinstance(todoist_raw, dict):
            todoist_raw = {}
        trello_raw = sync.get("trello", {})
        if not isinstance(trello_raw, dict):
            trello_raw = {}
        jira_raw = sync.get("jira", {})
        if not isinstance(jira_raw, dict):
            jira_raw = {}

        perms_raw = data.get("permissions", {})
        if not isinstance(perms_raw, dict):
            perms_raw = {}

        git_tracking_raw = data.get("git_tracking", {})
        if not isinstance(git_tracking_raw, dict):
            git_tracking_raw = {}

        archive_raw = data.get("archive", {})
        if not isinstance(archive_raw, dict):
            archive_raw = {}

        team_mode_raw = data.get("team_mode", {})
        if not isinstance(team_mode_raw, dict):
            team_mode_raw = {}

        resilience_raw = data.get("resilience", {})
        if not isinstance(resilience_raw, dict):
            resilience_raw = {}

        smart_gate_raw = data.get("smart_gate", {})
        if not isinstance(smart_gate_raw, dict):
            smart_gate_raw = {}

        pbd = data.get("projects_base_dir")

        return cls(
            tracking_dir=str(data.get("tracking_dir", "~/projects/tracking")),
            projects_base_dir=str(pbd) if isinstance(pbd, str) else None,
            git_integration=bool(data.get("git_integration", True)),
            default_priority=str(data.get("default_priority", "medium")),
            permissions=PermissionsConfig.from_dict(perms_raw),
            todoist=TodoistSync.from_dict(todoist_raw),
            trello=TrelloSync.from_dict(trello_raw),
            jira=JiraSync.from_dict(jira_raw),
            git_tracking=GitTracking.from_dict(git_tracking_raw),
            perms_integration=bool(data.get("perms_integration", False)),
            worktree_integration=bool(data.get("worktree_integration", False)),
            zoxide_integration=bool(data.get("zoxide_integration", False)),
            claudemd_management=bool(data.get("claudemd_management", False)),
            archive=ArchiveConfig.from_dict(archive_raw),
            team_mode=TeamModeConfig.from_dict(team_mode_raw),
            resilience=ResilienceConfig.from_dict(resilience_raw),
            smart_gate=SmartGateConfig.from_dict(smart_gate_raw),
            quality_level=str(data.get("quality_level", "balanced")),
            worktree_isolation=bool(data.get("worktree_isolation", False)),
        )


# ── Validation ────────────────────────────────────────────────────────────────


def validate_project_name(name: str) -> str | None:
    """Return an error message if *name* is invalid, or None if it is acceptable.

    Rejected patterns:
    - Empty or whitespace-only strings
    - Contains ``..`` (path traversal)
    - Contains ``/`` or ``\\`` (path separators)
    - Contains null bytes (``\\x00``)
    - Starts with ``.`` (hidden/reserved names such as ``.git``)
    - Contains newlines or other ASCII control characters (ordinals 0–31 and 127)
    """
    if not name or not name.strip():
        return "Project name must not be empty or whitespace-only."
    if ".." in name:
        return "Project name must not contain '..' (path traversal)."
    if "/" in name or "\\" in name:
        return "Project name must not contain path separators ('/' or '\\\\')."
    if "\x00" in name:
        return "Project name must not contain null bytes."
    if name.startswith("."):
        return "Project name must not start with '.' (reserved)."
    for ch in name:
        code = ord(ch)
        if code < 32 or code == 127:
            return f"Project name must not contain control characters (found ordinal {code})."
    return None


# ── Project index ─────────────────────────────────────────────────────────────


@dataclass
class ProjectEntry:
    """Lightweight index entry stored in active-projects.yaml."""

    name: str
    tracking_dir: str
    created: str
    archived: bool = False
    tags: list[str] = field(default_factory=list)
    archive_date: str | None = None
    purgeable: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tracking_dir": self.tracking_dir,
            "created": self.created,
            "archived": self.archived,
            "tags": self.tags,
            "archive_date": self.archive_date,
            "purgeable": self.purgeable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectEntry:
        tags = data.get("tags", [])
        return cls(
            name=str(data["name"]),
            tracking_dir=str(data["tracking_dir"]),
            created=str(data["created"]),
            archived=bool(data.get("archived", False)),
            tags=list(tags) if isinstance(tags, list) else [],
            archive_date=str(data["archive_date"]) if data.get("archive_date") else None,
            purgeable=bool(data.get("purgeable", True)),
        )


@dataclass
class ProjectIndex:
    version: int = 1
    projects: dict[str, ProjectEntry] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "projects": {k: v.to_dict() for k, v in self.projects.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectIndex:
        projects_raw = data.get("projects", {})
        if not isinstance(projects_raw, dict):
            projects_raw = {}
        # Note: old YAML files may contain an 'active' field — it is intentionally
        # ignored here (session-only concept now).
        return cls(
            version=int(data.get("version", 1)),
            projects={k: ProjectEntry.from_dict(v) for k, v in projects_raw.items()},  # type: ignore[arg-type]  # dict values are object; items are dicts at runtime
        )


# ── Project metadata ──────────────────────────────────────────────────────────


@dataclass
class RepoEntry:
    label: str
    path: str
    claudemd: bool = False
    reference: bool = False  # True = read-only context; no write perms, no git tracking

    def to_dict(self) -> dict[str, object]:
        return {"label": self.label, "path": self.path, "claudemd": self.claudemd, "reference": self.reference}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RepoEntry:
        return cls(
            label=str(data["label"]),
            path=str(data["path"]),
            claudemd=bool(data.get("claudemd", False)),
            reference=bool(data.get("reference", False)),
        )


@dataclass
class ProjectDates:
    created: str
    last_updated: str
    target: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"created": self.created, "last_updated": self.last_updated, "target": self.target}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectDates:
        return cls(
            created=str(data.get("created", "")),
            last_updated=str(data.get("last_updated", "")),
            target=data.get("target") if isinstance(data.get("target"), str) else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
        )


@dataclass
class ProjectPermissions:
    auto_grant: bool | None = None  # None = use global config default

    def to_dict(self) -> dict[str, object]:
        return {"auto_grant": self.auto_grant}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectPermissions:
        ag = data.get("auto_grant")
        return cls(auto_grant=bool(ag) if ag is not None else None)


@dataclass
class ProjectTodoistConfig:
    root_only: bool | None = None  # None = use global config default

    def to_dict(self) -> dict[str, object]:
        return {"root_only": self.root_only}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectTodoistConfig:
        ro = data.get("root_only")
        return cls(root_only=bool(ro) if ro is not None else None)


@dataclass
class ProjectTrelloConfig:
    """Per-project Trello config — overrides global TrelloSync defaults."""

    enabled: bool | None = None          # None = use global config default
    board_id: str | None = None          # Trello board ID for this project
    list_mappings: TrelloListMappings | None = None  # None = use global defaults
    on_delete: str | None = None         # "archive" | "delete" | None = use global default
    trello_tasks_checklist_id: str | None = None  # cached ID of the "Tasks" catch-all checklist

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "board_id": self.board_id,
            "list_mappings": self.list_mappings.to_dict() if self.list_mappings is not None else None,
            "on_delete": self.on_delete,
            "trello_tasks_checklist_id": self.trello_tasks_checklist_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectTrelloConfig:
        lm_raw = data.get("list_mappings")
        lm = TrelloListMappings.from_dict(lm_raw) if isinstance(lm_raw, dict) else None  # type: ignore[arg-type]
        enabled_raw = data.get("enabled")
        on_delete_raw = data.get("on_delete")
        board_id_raw = data.get("board_id")
        tcl_raw = data.get("trello_tasks_checklist_id")
        return cls(
            enabled=bool(enabled_raw) if enabled_raw is not None else None,
            board_id=str(board_id_raw) if isinstance(board_id_raw, str) else None,
            list_mappings=lm,
            on_delete=str(on_delete_raw) if isinstance(on_delete_raw, str) else None,
            trello_tasks_checklist_id=str(tcl_raw) if isinstance(tcl_raw, str) else None,
        )


@dataclass
class ProjectGitTrackingConfig:
    """Per-project git tracking config — overrides global GitTracking defaults."""

    enabled: bool | None = None
    github_enabled: bool | None = None
    github_repo_format: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "github_enabled": self.github_enabled,
            "github_repo_format": self.github_repo_format,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectGitTrackingConfig:
        enabled_raw = data.get("enabled")
        gh_raw = data.get("github_enabled")
        fmt_raw = data.get("github_repo_format")
        return cls(
            enabled=bool(enabled_raw) if enabled_raw is not None else None,
            github_enabled=bool(gh_raw) if gh_raw is not None else None,
            github_repo_format=str(fmt_raw) if isinstance(fmt_raw, str) else None,
        )


@dataclass
class ProjectMeta:
    name: str
    description: str = ""
    status: str = "active"  # active|paused|blocked|complete
    priority: str = "medium"
    repos: list[RepoEntry] = field(default_factory=list)
    dates: ProjectDates = field(default_factory=lambda: ProjectDates("", ""))
    tags: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    next_todo_id: int = 1
    git_enabled: bool = True
    todoist_project_id: str | None = None
    trello_card_id: str | None = None
    permissions: ProjectPermissions = field(default_factory=ProjectPermissions)
    todoist: ProjectTodoistConfig = field(default_factory=ProjectTodoistConfig)
    trello: ProjectTrelloConfig = field(default_factory=ProjectTrelloConfig)
    git_tracking: ProjectGitTrackingConfig = field(default_factory=ProjectGitTrackingConfig)
    zoxide_integration: bool | None = None  # None = use global config default
    claudemd_management: bool | None = None  # None = use global config default
    jira_issue_key: str | None = None  # set when project was created from a Jira epic; stable link
    jira_synced_comment_ids: list[str] = field(default_factory=list)  # Jira comment IDs already synced to NOTES.md

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "repos": [r.to_dict() for r in self.repos],
            "dates": self.dates.to_dict(),
            "tags": self.tags,
            "links": self.links,
            "next_todo_id": self.next_todo_id,
            "git_enabled": self.git_enabled,
            "todoist_project_id": self.todoist_project_id,
            "trello_card_id": self.trello_card_id,
            "permissions": self.permissions.to_dict(),
            "todoist": self.todoist.to_dict(),
            "trello": self.trello.to_dict(),
            "git_tracking": self.git_tracking.to_dict(),
            "zoxide_integration": self.zoxide_integration,
            "claudemd_management": self.claudemd_management,
            "jira_issue_key": self.jira_issue_key,
            "jira_synced_comment_ids": self.jira_synced_comment_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectMeta:
        repos_raw = data.get("repos", [])
        # Backward compat: old single-dir projects have a top-level `path` string
        # instead of `repos`. Auto-populate repos from legacy path on read (no disk write).
        if not (isinstance(repos_raw, list) and repos_raw):
            path_raw = data.get("path")
            if isinstance(path_raw, str) and path_raw:
                repos_raw = [{"label": "code", "path": path_raw, "claudemd": False, "reference": False}]
        links_raw = data.get("links", [])
        tags_raw = data.get("tags", [])
        perms_raw = data.get("permissions", {})
        dates_raw = data.get("dates", {})
        todoist_raw = data.get("todoist", {})
        trello_raw = data.get("trello", {})
        git_tracking_raw = data.get("git_tracking", {})

        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            status=str(data.get("status", "active")),
            priority=str(data.get("priority", "medium")),
            repos=[
                RepoEntry.from_dict(r) for r in (repos_raw if isinstance(repos_raw, list) else [])
            ],  # type: ignore[arg-type]  # list[object] from YAML; items are dicts at runtime
            dates=ProjectDates.from_dict(dates_raw if isinstance(dates_raw, dict) else {}),  # type: ignore[arg-type]  # object narrowed to dict but pyright can't verify
            tags=list(tags_raw) if isinstance(tags_raw, list) else [],
            links=list(links_raw) if isinstance(links_raw, list) else [],  # type: ignore[arg-type]  # list[object] expected as list[dict]; safe at runtime
            next_todo_id=int(data.get("next_todo_id", 1)),
            git_enabled=bool(data.get("git_enabled", True)),
            todoist_project_id=data.get("todoist_project_id")
            if isinstance(data.get("todoist_project_id"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            trello_card_id=data.get("trello_card_id")
            if isinstance(data.get("trello_card_id"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            permissions=ProjectPermissions.from_dict(
                perms_raw if isinstance(perms_raw, dict) else {}
            ),  # type: ignore[arg-type]  # object narrowed to dict but pyright can't verify
            todoist=ProjectTodoistConfig.from_dict(
                todoist_raw if isinstance(todoist_raw, dict) else {}
            ),  # type: ignore[arg-type]  # object narrowed to dict but pyright can't verify
            trello=ProjectTrelloConfig.from_dict(
                trello_raw if isinstance(trello_raw, dict) else {}
            ),  # type: ignore[arg-type]  # object narrowed to dict but pyright can't verify
            git_tracking=ProjectGitTrackingConfig.from_dict(
                git_tracking_raw if isinstance(git_tracking_raw, dict) else {}
            ),  # type: ignore[arg-type]  # object narrowed to dict but pyright can't verify
            zoxide_integration=bool(zi_raw) if (zi_raw := data.get("zoxide_integration")) is not None else None,
            claudemd_management=bool(cm_raw) if (cm_raw := data.get("claudemd_management")) is not None else None,
            jira_issue_key=data.get("jira_issue_key")
            if isinstance(data.get("jira_issue_key"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            jira_synced_comment_ids=[str(x) for x in data.get("jira_synced_comment_ids", [])] if isinstance(data.get("jira_synced_comment_ids"), list) else [],
        )


# ── Todos ─────────────────────────────────────────────────────────────────────


@dataclass
class TrelloSyncState:
    """Snapshot of last-synced state for a todo's Trello representation."""

    last_sync: str = ""       # ISO 8601 datetime of last successful sync
    synced_name: str = ""     # name as it was on Trello after last sync
    synced_state: str = ""    # "complete" or "incomplete" after last sync

    def to_dict(self) -> dict[str, object]:
        return {
            "last_sync": self.last_sync,
            "synced_name": self.synced_name,
            "synced_state": self.synced_state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TrelloSyncState:
        return cls(
            last_sync=str(data.get("last_sync", "")),
            synced_name=str(data.get("synced_name", "")),
            synced_state=str(data.get("synced_state", "")),
        )


@dataclass
class TodoGit:
    branch: str | None = None
    commits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"branch": self.branch, "commits": self.commits}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TodoGit:
        commits = data.get("commits", [])
        return cls(
            branch=data.get("branch") if isinstance(data.get("branch"), str) else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            commits=list(commits) if isinstance(commits, list) else [],
        )


@dataclass
class Todo:
    id: str
    title: str
    status: str = "pending"
    priority: str = "medium"
    created: str = ""
    updated: str = ""
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    next_child_id: int = 1
    tags: list[str] = field(default_factory=list)
    git: TodoGit = field(default_factory=TodoGit)
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    notes: str = ""
    has_requirements: bool = False
    has_research: bool = False
    todoist_task_id: str | None = None
    todoist_description_synced: str = ""  # last Todoist description pulled; used to detect changes and avoid duplicate appends
    trello_card_id: str | None = None  # set when synced with Trello; stable link to the Trello card
    trello_checklist_id: str | None = None  # set for root todos that become Trello checklists
    trello_checklist_item_id: str | None = None  # set for todos that become Trello checklist items
    jira_issue_key: str | None = None  # set when synced with Jira; stable link to the Jira issue
    jira_synced_comment_ids: list[str] = field(default_factory=list)  # Jira comment IDs already pulled into notes
    due_date: str | None = None  # ISO 8601 date string (YYYY-MM-DD) or None
    trello_sync_state: TrelloSyncState | None = None  # last-synced snapshot for Trello

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "status": getattr(self.status, "value", self.status),
            "priority": getattr(self.priority, "value", self.priority),
            "created": self.created,
            "updated": self.updated,
            "parent": self.parent,
            "children": self.children,
            "next_child_id": self.next_child_id,
            "tags": self.tags,
            "git": self.git.to_dict(),
            "blocks": self.blocks,
            "blocked_by": self.blocked_by,
            "notes": self.notes,
            "has_requirements": self.has_requirements,
            "has_research": self.has_research,
            "todoist_task_id": self.todoist_task_id,
            "todoist_description_synced": self.todoist_description_synced,
            "trello_card_id": self.trello_card_id,
            "trello_checklist_id": self.trello_checklist_id,
            "trello_checklist_item_id": self.trello_checklist_item_id,
            "jira_issue_key": self.jira_issue_key,
            "jira_synced_comment_ids": self.jira_synced_comment_ids,
            "due_date": self.due_date,
            "trello_sync_state": self.trello_sync_state.to_dict() if self.trello_sync_state is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Todo:
        git_raw = data.get("git", {})
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            status=str(data.get("status", "pending")),
            priority=str(data.get("priority", "medium")),
            created=str(data.get("created", "")),
            updated=str(data.get("updated", "")),
            parent=data.get("parent") if isinstance(data.get("parent"), str) else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            children=list(data.get("children", [])),  # type: ignore[arg-type]  # object from dict.get; list[str] at runtime
            next_child_id=int(data.get("next_child_id", 1)),
            tags=list(data.get("tags", [])),  # type: ignore[arg-type]  # object from dict.get; list[str] at runtime
            git=TodoGit.from_dict(git_raw if isinstance(git_raw, dict) else {}),  # type: ignore[arg-type]  # object narrowed to dict but pyright can't verify
            blocks=list(data.get("blocks", [])),  # type: ignore[arg-type]  # object from dict.get; list[str] at runtime
            blocked_by=list(data.get("blocked_by", [])),  # type: ignore[arg-type]  # object from dict.get; list[str] at runtime
            notes=str(data.get("notes", "")),
            has_requirements=bool(data.get("has_requirements", False)),
            has_research=bool(data.get("has_research", False)),
            todoist_task_id=data.get("todoist_task_id")
            if isinstance(data.get("todoist_task_id"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            todoist_description_synced=str(data.get("todoist_description_synced", "")),
            trello_card_id=data.get("trello_card_id")
            if isinstance(data.get("trello_card_id"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            trello_checklist_id=data.get("trello_checklist_id")
            if isinstance(data.get("trello_checklist_id"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            trello_checklist_item_id=data.get("trello_checklist_item_id")
            if isinstance(data.get("trello_checklist_item_id"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            jira_issue_key=data.get("jira_issue_key")
            if isinstance(data.get("jira_issue_key"), str)
            else None,  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            jira_synced_comment_ids=[str(x) for x in jsci] if isinstance((jsci := data.get("jira_synced_comment_ids")), list) else [],
            due_date=data.get("due_date", None)  # type: ignore[arg-type]  # conditional narrows to str|None but pyright sees object
            if isinstance(data.get("due_date"), str)
            else None,
            trello_sync_state=TrelloSyncState.from_dict(tss_raw)  # type: ignore[arg-type]
            if isinstance((tss_raw := data.get("trello_sync_state")), dict)
            else None,
        )
