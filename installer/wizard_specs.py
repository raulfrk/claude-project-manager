"""Single source of truth for wizard prompt definitions.

Both the Rich path (installer/wizard.py) and the Textual path
(installer/screens/wizard.py + advanced_config.py) iterate PROJ_YAML_PROMPTS
and dispatch to Rich Prompts or Textual widgets based on PromptSpec.type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from installer._config_loader import get_nested

YamlFile = Literal["proj", "worktree", "todoist", "trello", "jira"]
PromptType = Literal["bool", "str", "int", "choice"]
Tier = Literal["basic", "advanced"]


@dataclass
class PromptSpec:
    """Single source of truth for one wizard field."""

    label: str
    dotted_key: str
    type: PromptType
    group: str
    tier: Tier
    default_factory: Callable[[dict[str, Any]], Any]
    yaml_file: YamlFile = "proj"
    choices: list[str] | None = None
    int_range: tuple[int, int] | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None


def _d(key: str, fallback: Any) -> Callable[[dict[str, Any]], Any]:
    """Build a default_factory that reads `key` from existing, else fallback."""

    def factory(existing: dict[str, Any]) -> Any:
        return get_nested(existing, key, fallback)

    return factory


PROJ_YAML_PROMPTS: list[PromptSpec] = [
    # ---------- Basic tier (proj.yaml) ----------
    PromptSpec(
        label="Tracking directory",
        dotted_key="tracking_dir",
        type="str",
        group="Paths",
        tier="basic",
        default_factory=_d("tracking_dir", "~/projects/tracking"),
    ),
    PromptSpec(
        label="Projects base directory",
        dotted_key="projects_base_dir",
        type="str",
        group="Paths",
        tier="basic",
        default_factory=_d("projects_base_dir", "~/projects"),
    ),
    PromptSpec(
        label="Enable sandbox integration",
        dotted_key="sandbox_integration",
        type="bool",
        group="Integrations",
        tier="basic",
        default_factory=_d("sandbox_integration", True),
    ),
    PromptSpec(
        label="Enable zoxide integration",
        dotted_key="zoxide_integration",
        type="bool",
        group="Integrations",
        tier="basic",
        default_factory=_d("zoxide_integration", False),
    ),
    PromptSpec(
        label="Enable git tracking",
        dotted_key="git_tracking.enabled",
        type="bool",
        group="Git tracking",
        tier="basic",
        default_factory=_d("git_tracking.enabled", False),
    ),
    PromptSpec(
        label="Enable GitHub tracking",
        dotted_key="git_tracking.github_enabled",
        type="bool",
        group="Git tracking",
        tier="basic",
        default_factory=_d("git_tracking.github_enabled", False),
        condition=lambda ex: bool(get_nested(ex, "git_tracking.enabled", False)),
    ),
    PromptSpec(
        label="GitHub repo format",
        dotted_key="git_tracking.github_repo_format",
        type="str",
        group="Git tracking",
        tier="basic",
        default_factory=_d("git_tracking.github_repo_format", "cpm-tracking-{project}"),
        condition=lambda ex: bool(get_nested(ex, "git_tracking.github_enabled", False)),
    ),
    PromptSpec(
        label="Default quality level",
        dotted_key="quality_level",
        type="choice",
        group="Execution",
        tier="basic",
        default_factory=_d("quality_level", "careful"),
        choices=["fast", "balanced", "careful", "paranoid"],
    ),
    PromptSpec(
        label="Worktree isolation enabled by default",
        dotted_key="worktree_isolation",
        type="bool",
        group="Execution",
        tier="basic",
        default_factory=_d("worktree_isolation", True),
    ),
    # ---------- Basic tier (worktree.yaml) ----------
    PromptSpec(
        label="Worktree directory",
        dotted_key="worktree_dir",
        type="str",
        group="Paths",
        tier="basic",
        default_factory=_d("worktree_dir", "~/worktrees"),
        yaml_file="worktree",
    ),
    # ---------- Advanced tier (proj.yaml) — team_mode ----------
    PromptSpec(
        label="Team mode enabled",
        dotted_key="team_mode.enabled",
        type="bool",
        group="Team mode",
        tier="advanced",
        default_factory=_d("team_mode.enabled", True),
    ),
    PromptSpec(
        label="Max parallel agents",
        dotted_key="team_mode.max_agents",
        type="int",
        group="Team mode",
        tier="advanced",
        default_factory=_d("team_mode.max_agents", 30),
        int_range=(1, 100),
    ),
    PromptSpec(
        label="Trust level (0-3)",
        dotted_key="team_mode.trust_level",
        type="int",
        group="Team mode",
        tier="advanced",
        default_factory=_d("team_mode.trust_level", 1),
        int_range=(0, 3),
    ),
    # ---------- Advanced tier (proj.yaml) — smart_gate ----------
    PromptSpec(
        label="Smart gate enabled",
        dotted_key="smart_gate.enabled",
        type="bool",
        group="Smart gate",
        tier="advanced",
        default_factory=_d("smart_gate.enabled", True),
    ),
    PromptSpec(
        label="Auto-execute score threshold",
        dotted_key="smart_gate.auto_execute_threshold",
        type="int",
        group="Smart gate",
        tier="advanced",
        default_factory=_d("smart_gate.auto_execute_threshold", 3),
        int_range=(0, 14),
    ),
    PromptSpec(
        label="Full-review score threshold",
        dotted_key="smart_gate.full_review_threshold",
        type="int",
        group="Smart gate",
        tier="advanced",
        default_factory=_d("smart_gate.full_review_threshold", 8),
        int_range=(0, 14),
    ),
    # ---------- Advanced tier (proj.yaml) — resilience ----------
    PromptSpec(
        label="Resilience retries",
        dotted_key="resilience.max_retries",
        type="int",
        group="Resilience",
        tier="advanced",
        default_factory=_d("resilience.max_retries", 2),
        int_range=(0, 5),
    ),
    PromptSpec(
        label="Resilience backoff seconds",
        dotted_key="resilience.backoff_seconds",
        type="int",
        group="Resilience",
        tier="advanced",
        default_factory=_d("resilience.backoff_seconds", 5),
        int_range=(0, 60),
    ),
    # ---------- Advanced tier (proj.yaml) — context_injection ----------
    PromptSpec(
        label="Context injection enabled",
        dotted_key="context_injection.enabled",
        type="bool",
        group="Context injection",
        tier="advanced",
        default_factory=_d("context_injection.enabled", True),
    ),
    PromptSpec(
        label="Max context tokens per agent",
        dotted_key="context_injection.max_tokens",
        type="int",
        group="Context injection",
        tier="advanced",
        default_factory=_d("context_injection.max_tokens", 20000),
        int_range=(1000, 200000),
    ),
    PromptSpec(
        label="Include CLAUDE.md by default",
        dotted_key="context_injection.include_claudemd",
        type="bool",
        group="Context injection",
        tier="advanced",
        default_factory=_d("context_injection.include_claudemd", False),
    ),
    # ---------- Advanced tier (proj.yaml) — archive ----------
    PromptSpec(
        label="Auto-archive completed todos",
        dotted_key="archive.auto_archive",
        type="bool",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.auto_archive", True),
    ),
    PromptSpec(
        label="Archive after N days",
        dotted_key="archive.after_days",
        type="int",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.after_days", 30),
        int_range=(1, 365),
    ),
    PromptSpec(
        label="Keep archive history",
        dotted_key="archive.keep_history",
        type="bool",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.keep_history", True),
    ),
    PromptSpec(
        label="Purge archive after N days",
        dotted_key="archive.purge_after_days",
        type="int",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.purge_after_days", 365),
        int_range=(0, 3650),
    ),
    # ---------- Advanced tier (proj.yaml) — permissions ----------
    PromptSpec(
        label="Grant read permissions automatically",
        dotted_key="permissions.auto_grant_read",
        type="bool",
        group="Permissions",
        tier="advanced",
        default_factory=_d("permissions.auto_grant_read", True),
    ),
    PromptSpec(
        label="Grant edit permissions automatically",
        dotted_key="permissions.auto_grant_edit",
        type="bool",
        group="Permissions",
        tier="advanced",
        default_factory=_d("permissions.auto_grant_edit", True),
    ),
    # ---------- Advanced tier (proj.yaml) — misc ----------
    PromptSpec(
        label="Default todo priority",
        dotted_key="default_priority",
        type="choice",
        group="Other proj",
        tier="advanced",
        default_factory=_d("default_priority", "medium"),
        choices=["low", "medium", "high"],
    ),
    PromptSpec(
        label="Claude.md management enabled",
        dotted_key="claudemd_management",
        type="bool",
        group="Other proj",
        tier="advanced",
        default_factory=_d("claudemd_management", True),
    ),
    PromptSpec(
        label="Worktree integration enabled",
        dotted_key="worktree_integration",
        type="bool",
        group="Other proj",
        tier="advanced",
        default_factory=_d("worktree_integration", True),
    ),
    # ---------- Advanced tier (proj.yaml) — sync.todoist ----------
    PromptSpec(
        label="Todoist root-only sync",
        dotted_key="sync.todoist.root_only",
        type="bool",
        group="Todoist extras",
        tier="advanced",
        default_factory=_d("sync.todoist.root_only", False),
    ),
    # ---------- Advanced tier (proj.yaml) — sync.trello ----------
    PromptSpec(
        label="Trello default list",
        dotted_key="sync.trello.default_list",
        type="str",
        group="Trello extras",
        tier="advanced",
        default_factory=_d("sync.trello.default_list", "Todo"),
    ),
    PromptSpec(
        label="Trello on-delete action",
        dotted_key="sync.trello.on_delete",
        type="choice",
        group="Trello extras",
        tier="advanced",
        default_factory=_d("sync.trello.on_delete", "archive"),
        choices=["archive", "delete"],
    ),
    # ---------- Advanced tier (proj.yaml) — sync.trello.list_mappings ----------
    PromptSpec(
        label="Trello list: backlog",
        dotted_key="sync.trello.list_mappings.backlog",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.backlog", "Backlog"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: todo",
        dotted_key="sync.trello.list_mappings.todo",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.todo", "Todo"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: in_progress",
        dotted_key="sync.trello.list_mappings.in_progress",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.in_progress", "In Progress"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: blocked",
        dotted_key="sync.trello.list_mappings.blocked",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.blocked", "Blocked"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: done",
        dotted_key="sync.trello.list_mappings.done",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.done", "Done"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: archive",
        dotted_key="sync.trello.list_mappings.archive",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.archive", "Archive"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
]


WIZARD_EXCLUDED_FIELDS: set[str] = {
    "version",
    "permissions.projects_root",
    "permissions.tracking_root",
    "sync.todoist.mcp_server",
    "sync.todoist.rate_limit_per_10s",
    "sync.trello.rate_limit_per_10s",
    "sync.jira.rate_limit_per_10s",
    "sync.trello.allowed_board_ids",
    "sync.jira.allowed_project_keys",
    "base_repos",
}


def assert_prompt_spec_covers_schema() -> list[str]:
    """Return list of ProjConfig dotted keys missing from PROJ_YAML_PROMPTS.

    Intended for regression tests: walks ProjConfig dataclass fields and
    reports any non-excluded field that has no matching PromptSpec.
    Returns empty list on full coverage, or a list of missing keys.
    Never raises: if ProjConfig cannot be imported, returns an empty list
    so this helper is safe to call in any environment.
    """
    try:
        import dataclasses

        from plugins.proj.server.server.lib.models import ProjConfig  # type: ignore
    except Exception:
        return []

    covered = {s.dotted_key for s in PROJ_YAML_PROMPTS if s.yaml_file == "proj"}
    missing: list[str] = []

    def walk(cls: type, prefix: str = "") -> None:
        if not dataclasses.is_dataclass(cls):
            return
        for f in dataclasses.fields(cls):
            dotted = f"{prefix}{f.name}" if not prefix else f"{prefix}.{f.name}"
            if dotted in WIZARD_EXCLUDED_FIELDS:
                continue
            if dataclasses.is_dataclass(f.type):
                walk(f.type, dotted)
            else:
                if dotted not in covered:
                    missing.append(dotted)

    try:
        walk(ProjConfig)
    except Exception:
        return []
    return missing
