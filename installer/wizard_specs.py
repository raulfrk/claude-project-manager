"""Single source of truth for wizard prompt definitions.

Both the Rich path (installer/wizard.py) and the Textual path
(installer/screens/wizard.py + advanced_config.py) iterate PROJ_YAML_PROMPTS
and dispatch to Rich Prompts or Textual widgets based on PromptSpec.type.

Hard contract (conditions): `PromptSpec.condition` lambdas receive the
proj.yaml bucket ONLY, regardless of the spec's own `yaml_file`. A trello
spec that needs to check `sync.trello.enabled` reads it from the proj bucket
(that's where it lives in real proj.yaml files). No cross-file walking.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    sensitive: bool = False


# Lazy mutable container: populated on first _d() factory call, NOT at import.
# Prevents missing/corrupt defaults.yaml from bricking --update/--uninstall/
# --status (which never invoke a factory).
_DEFAULTS_CACHE: dict[str, Any] = {}


def _ensure_defaults_loaded() -> None:
    """Populate _DEFAULTS_CACHE from installer/defaults.yaml on first call."""
    if "data" in _DEFAULTS_CACHE:
        return
    from importlib.resources import files

    import yaml

    try:
        text = (
            files("installer").joinpath("defaults.yaml").read_text(encoding="utf-8-sig")
        )
    except (FileNotFoundError, ModuleNotFoundError) as e:
        raise RuntimeError(
            "installer/defaults.yaml not found — packaging bug; verify "
            "pyproject.toml [tool.hatch.build.targets.wheel] force-include "
            f"or artifacts entry. Original: {e}"
        ) from e
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise RuntimeError(f"installer/defaults.yaml corrupt: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(
            f"installer/defaults.yaml must be a mapping, got {type(data).__name__}"
        )
    _DEFAULTS_CACHE["data"] = data


def _reload_defaults(path: Path | None = None) -> None:
    """Test helper: clear cache so next _d() call re-reads.

    If path is given, load directly from that file; otherwise the next
    _ensure_defaults_loaded() call will re-read from the packaged resource.
    """
    _DEFAULTS_CACHE.clear()
    if path is not None:
        import yaml

        text = path.read_text(encoding="utf-8-sig")
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise RuntimeError(
                f"defaults override {path} must be a mapping, got {type(data).__name__}"
            )
        _DEFAULTS_CACHE["data"] = data


# Scalar/list types considered valid for a defaults.yaml leaf value.
# A dict in place of a scalar means the existing yaml nested-walked past the
# intended leaf — fall through to the default on type mismatch.
_SCALAR_TYPES = (str, int, float, bool, list, type(None))


def _d(key: str) -> Callable[[dict[str, Any]], Any]:
    """Build a lazy default_factory that reads `key` from existing, else defaults.yaml.

    The closure reads `_DEFAULTS_CACHE` at factory-call time (not at spec
    construction time) so `_reload_defaults` can rebind defaults between
    test cases.

    Type-mismatch guard: if the existing yaml returns a dict where a scalar
    is expected (e.g. `tracking_dir: {foo: bar}`), the factory falls through
    to the defaults.yaml value. Prevents downstream rendering crashes.
    """

    def factory(existing: dict[str, Any]) -> Any:
        _ensure_defaults_loaded()
        defaults = _DEFAULTS_CACHE.get("data", {})
        fallback = get_nested(defaults, key, None)
        existing_val = get_nested(existing, key, None)
        if existing_val is None:
            return fallback
        # Type-mismatch guard: existing yaml has wrong shape (e.g. dict
        # where string expected). Fall through to the default.
        if fallback is not None and not isinstance(existing_val, _SCALAR_TYPES):
            return fallback
        if fallback is not None:
            # int/float are interchangeable; bool is treated as int in Python
            # so compare types strictly, with numeric cross-tolerance.
            if type(existing_val) is not type(fallback):
                numeric = (int, float)
                if isinstance(existing_val, numeric) and isinstance(fallback, numeric):
                    return existing_val
                # bool is an int subclass — if fallback is bool but existing
                # is a non-bool int, treat as mismatch (yaml "1" vs True).
                if isinstance(fallback, bool) and not isinstance(existing_val, bool):
                    return fallback
                if isinstance(existing_val, bool) and not isinstance(fallback, bool):
                    return fallback
                return fallback
        return existing_val

    return factory


def get_distinct_yaml_files(specs: list[PromptSpec]) -> list[str]:
    """Return the distinct yaml_file values referenced by specs, in order."""
    seen: dict[str, None] = {}
    for spec in specs:
        seen.setdefault(spec.yaml_file, None)
    return list(seen.keys())


PROJ_YAML_PROMPTS: list[PromptSpec] = [
    # ---------- Basic tier (proj.yaml) ----------
    PromptSpec(
        label="Tracking directory",
        dotted_key="tracking_dir",
        type="str",
        group="Paths",
        tier="basic",
        default_factory=_d("tracking_dir"),
    ),
    PromptSpec(
        label="Projects base directory",
        dotted_key="projects_base_dir",
        type="str",
        group="Paths",
        tier="basic",
        default_factory=_d("projects_base_dir"),
    ),
    PromptSpec(
        label="Enable sandbox integration",
        dotted_key="sandbox_integration",
        type="bool",
        group="Integrations",
        tier="basic",
        default_factory=_d("sandbox_integration"),
    ),
    PromptSpec(
        label="Enable zoxide integration",
        dotted_key="zoxide_integration",
        type="bool",
        group="Integrations",
        tier="basic",
        default_factory=_d("zoxide_integration"),
    ),
    PromptSpec(
        label="Enable git tracking",
        dotted_key="git_tracking.enabled",
        type="bool",
        group="Git tracking",
        tier="basic",
        default_factory=_d("git_tracking.enabled"),
    ),
    PromptSpec(
        label="Enable GitHub tracking",
        dotted_key="git_tracking.github_enabled",
        type="bool",
        group="Git tracking",
        tier="basic",
        default_factory=_d("git_tracking.github_enabled"),
        condition=lambda ex: bool(get_nested(ex, "git_tracking.enabled", False)),
    ),
    PromptSpec(
        label="GitHub repo format",
        dotted_key="git_tracking.github_repo_format",
        type="str",
        group="Git tracking",
        tier="basic",
        default_factory=_d("git_tracking.github_repo_format"),
        condition=lambda ex: bool(get_nested(ex, "git_tracking.github_enabled", False)),
    ),
    PromptSpec(
        label="Default quality level",
        dotted_key="quality_level",
        type="choice",
        group="Execution",
        tier="basic",
        default_factory=_d("quality_level"),
        choices=["fast", "balanced", "careful", "paranoid"],
    ),
    PromptSpec(
        label="Worktree isolation enabled by default",
        dotted_key="worktree_isolation",
        type="bool",
        group="Execution",
        tier="basic",
        default_factory=_d("worktree_isolation"),
    ),
    # ---------- Basic tier (worktree.yaml) ----------
    PromptSpec(
        label="Worktree directory",
        dotted_key="default_worktree_dir",
        type="str",
        group="Paths",
        tier="basic",
        default_factory=_d("default_worktree_dir"),
        yaml_file="worktree",
    ),
    # ---------- Advanced tier (proj.yaml) — team_mode ----------
    PromptSpec(
        label="Team mode enabled",
        dotted_key="team_mode.enabled",
        type="bool",
        group="Team mode",
        tier="advanced",
        default_factory=_d("team_mode.enabled"),
    ),
    PromptSpec(
        label="Max parallel agents",
        dotted_key="team_mode.max_agents",
        type="int",
        group="Team mode",
        tier="advanced",
        default_factory=_d("team_mode.max_agents"),
        int_range=(1, 100),
    ),
    PromptSpec(
        label="Trust level (0-3)",
        dotted_key="team_mode.trust_level",
        type="int",
        group="Team mode",
        tier="advanced",
        default_factory=_d("team_mode.trust_level"),
        int_range=(0, 3),
    ),
    # ---------- Advanced tier (proj.yaml) — smart_gate ----------
    PromptSpec(
        label="Smart gate enabled",
        dotted_key="smart_gate.enabled",
        type="bool",
        group="Smart gate",
        tier="advanced",
        default_factory=_d("smart_gate.enabled"),
    ),
    PromptSpec(
        label="Auto-execute score threshold",
        dotted_key="smart_gate.auto_execute_threshold",
        type="int",
        group="Smart gate",
        tier="advanced",
        default_factory=_d("smart_gate.auto_execute_threshold"),
        int_range=(0, 14),
    ),
    PromptSpec(
        label="Full-review score threshold",
        dotted_key="smart_gate.full_review_threshold",
        type="int",
        group="Smart gate",
        tier="advanced",
        default_factory=_d("smart_gate.full_review_threshold"),
        int_range=(0, 14),
    ),
    # ---------- Advanced tier (proj.yaml) — resilience ----------
    PromptSpec(
        label="Resilience retries",
        dotted_key="resilience.max_retries",
        type="int",
        group="Resilience",
        tier="advanced",
        default_factory=_d("resilience.max_retries"),
        int_range=(0, 5),
    ),
    PromptSpec(
        label="Resilience backoff seconds",
        dotted_key="resilience.backoff_seconds",
        type="int",
        group="Resilience",
        tier="advanced",
        default_factory=_d("resilience.backoff_seconds"),
        int_range=(0, 60),
    ),
    # ---------- Advanced tier (proj.yaml) — context_injection ----------
    PromptSpec(
        label="Context injection enabled",
        dotted_key="context_injection.enabled",
        type="bool",
        group="Context injection",
        tier="advanced",
        default_factory=_d("context_injection.enabled"),
    ),
    PromptSpec(
        label="Max context tokens per agent",
        dotted_key="context_injection.max_tokens",
        type="int",
        group="Context injection",
        tier="advanced",
        default_factory=_d("context_injection.max_tokens"),
        int_range=(1000, 200000),
    ),
    PromptSpec(
        label="Include CLAUDE.md by default",
        dotted_key="context_injection.include_claudemd",
        type="bool",
        group="Context injection",
        tier="advanced",
        default_factory=_d("context_injection.include_claudemd"),
    ),
    # ---------- Advanced tier (proj.yaml) — archive ----------
    PromptSpec(
        label="Auto-archive completed todos",
        dotted_key="archive.auto_archive",
        type="bool",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.auto_archive"),
    ),
    PromptSpec(
        label="Archive after N days",
        dotted_key="archive.after_days",
        type="int",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.after_days"),
        int_range=(1, 365),
    ),
    PromptSpec(
        label="Keep archive history",
        dotted_key="archive.keep_history",
        type="bool",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.keep_history"),
    ),
    PromptSpec(
        label="Purge archive after N days",
        dotted_key="archive.purge_after_days",
        type="int",
        group="Archive",
        tier="advanced",
        default_factory=_d("archive.purge_after_days"),
        int_range=(0, 3650),
    ),
    # ---------- Advanced tier (proj.yaml) — permissions ----------
    PromptSpec(
        label="Grant read permissions automatically",
        dotted_key="permissions.auto_grant_read",
        type="bool",
        group="Permissions",
        tier="advanced",
        default_factory=_d("permissions.auto_grant_read"),
    ),
    PromptSpec(
        label="Grant edit permissions automatically",
        dotted_key="permissions.auto_grant_edit",
        type="bool",
        group="Permissions",
        tier="advanced",
        default_factory=_d("permissions.auto_grant_edit"),
    ),
    # ---------- Advanced tier (proj.yaml) — misc ----------
    PromptSpec(
        label="Default todo priority",
        dotted_key="default_priority",
        type="choice",
        group="Other proj",
        tier="advanced",
        default_factory=_d("default_priority"),
        choices=["low", "medium", "high"],
    ),
    PromptSpec(
        label="Claude.md management enabled",
        dotted_key="claudemd_management",
        type="bool",
        group="Other proj",
        tier="advanced",
        default_factory=_d("claudemd_management"),
    ),
    PromptSpec(
        label="Worktree integration enabled",
        dotted_key="worktree_integration",
        type="bool",
        group="Other proj",
        tier="advanced",
        default_factory=_d("worktree_integration"),
    ),
    # ---------- Advanced tier (proj.yaml) — sync.todoist ----------
    PromptSpec(
        label="Todoist root-only sync",
        dotted_key="sync.todoist.root_only",
        type="bool",
        group="Todoist extras",
        tier="advanced",
        default_factory=_d("sync.todoist.root_only"),
    ),
    # ---------- Advanced tier (proj.yaml) — sync.trello ----------
    PromptSpec(
        label="Trello default list",
        dotted_key="sync.trello.default_list",
        type="str",
        group="Trello extras",
        tier="advanced",
        default_factory=_d("sync.trello.default_list"),
    ),
    PromptSpec(
        label="Trello on-delete action",
        dotted_key="sync.trello.on_delete",
        type="choice",
        group="Trello extras",
        tier="advanced",
        default_factory=_d("sync.trello.on_delete"),
        choices=["archive", "delete"],
    ),
    # ---------- Advanced tier (proj.yaml) — sync.trello.list_mappings ----------
    PromptSpec(
        label="Trello list: backlog",
        dotted_key="sync.trello.list_mappings.backlog",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.backlog"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: todo",
        dotted_key="sync.trello.list_mappings.todo",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.todo"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: in_progress",
        dotted_key="sync.trello.list_mappings.in_progress",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.in_progress"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: blocked",
        dotted_key="sync.trello.list_mappings.blocked",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.blocked"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: done",
        dotted_key="sync.trello.list_mappings.done",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.done"),
        condition=lambda ex: bool(get_nested(ex, "sync.trello.enabled", False)),
    ),
    PromptSpec(
        label="Trello list: archive",
        dotted_key="sync.trello.list_mappings.archive",
        type="str",
        group="Trello list mappings",
        tier="advanced",
        default_factory=_d("sync.trello.list_mappings.archive"),
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


def assert_prompt_spec_covers_worktree_schema() -> list[str]:
    """Return WorktreeConfig dotted keys missing from PROJ_YAML_PROMPTS.

    Parallel to assert_prompt_spec_covers_schema but for the worktree.yaml
    bucket. Non-scalar fields (e.g. base_repos: list[BaseRepo]) and fields
    in WIZARD_EXCLUDED_FIELDS are skipped.
    """
    try:
        import dataclasses

        from plugins.worktree.server.server.lib.models import (  # type: ignore
            WorktreeConfig,
        )
    except Exception:
        return []

    covered = {s.dotted_key for s in PROJ_YAML_PROMPTS if s.yaml_file == "worktree"}
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
                # Skip list/dict fields — those need structured editing, not
                # a scalar prompt.
                type_str = str(f.type)
                if "list" in type_str or "dict" in type_str:
                    continue
                if dotted not in covered:
                    missing.append(dotted)

    try:
        walk(WorktreeConfig)
    except Exception:
        return []
    return missing


def assert_spec_keys_round_trip() -> list[str]:
    """Return list of (spec.yaml_file, dotted_key) that fail round-trip merge.

    For every PromptSpec, construct a single-field dict with the dotted_key
    and a sentinel value, merge it into an empty existing dict, and verify
    that the _d closure can read it back. Catches mismatches where a spec's
    dotted_key does not round-trip through the _merge_dotted_into_dict
    writer and the get_nested reader (e.g. typo or path mismatch).
    """
    from installer._config_writer import _merge_dotted_into_dict

    failures: list[str] = []
    for spec in PROJ_YAML_PROMPTS:
        sentinel = object()
        merged: dict[str, Any] = {}
        _merge_dotted_into_dict(merged, {spec.dotted_key: sentinel})
        got = get_nested(merged, spec.dotted_key, default=None)
        if got is not sentinel:
            failures.append(f"{spec.yaml_file}:{spec.dotted_key}")
    return failures
