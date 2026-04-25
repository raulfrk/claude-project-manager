# installer/flow/wizard.py
"""prompt_toolkit replacement for Textual WizardScreen.

Loads existing ~/.claude/<bucket>.yaml values, iterates PROJ_YAML_PROMPTS
(tier="basic" only), builds FieldSpec list with defaults pre-filled from
existing yaml, calls run_form.

Returns dict of submitted values keyed by PromptSpec.dotted_key, or None
on cancel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.flow.form import FieldSpec, run_form
from installer.wizard import _create_shared_venv_step
from installer.wizard_specs import PROJ_YAML_PROMPTS, get_distinct_yaml_files

_PROJ_PLUGINS = {"proj", "router", "todoist", "trello", "jira", "confluence"}


def _spec_to_field_kind(spec_type: str, sensitive: bool) -> str:
    """Map PromptSpec.type + sensitive → FieldSpec.kind."""
    if spec_type == "str" and sensitive:
        return "password"
    mapping = {"bool": "bool", "str": "text", "int": "int", "choice": "select"}
    return mapping.get(spec_type, "text")


def _load_bucket(bucket: str, claude_home: Path) -> dict[str, Any]:
    path = claude_home / f"{bucket}.yaml"
    if not path.exists():
        return {}
    try:
        return load_existing_yaml(path) or {}
    except ConfigLoadError:
        return {}


def run_wizard(state: Any, args: Any, console: Console) -> dict[str, Any] | None:
    claude_home = Path.home() / ".claude"

    buckets: dict[str, dict[str, Any]] = {}
    for bucket_name in get_distinct_yaml_files(PROJ_YAML_PROMPTS):
        buckets[bucket_name] = _load_bucket(bucket_name, claude_home)

    selected = set(getattr(state, "installed_plugins", []))
    needs_proj = bool(_PROJ_PLUGINS & selected)
    needs_worktree = "worktree" in selected

    proj_bucket = buckets.get("proj", {})
    fields: list[FieldSpec] = []

    for spec in PROJ_YAML_PROMPTS:
        if spec.tier != "basic":
            continue
        if spec.yaml_file == "proj" and not needs_proj:
            continue
        if spec.yaml_file == "worktree" and not needs_worktree:
            continue
        if spec.condition is not None and not spec.condition(proj_bucket):
            continue

        bucket = buckets.get(spec.yaml_file, {})
        default = spec.default_factory(bucket)
        fields.append(
            FieldSpec(
                key=spec.dotted_key,
                label=spec.label,
                kind=_spec_to_field_kind(spec.type, spec.sensitive),
                default=default,
                choices=list(spec.choices) if spec.choices else None,
                group=spec.group,
            )
        )

    result = run_form(fields, console, title="Configuration Wizard")
    _create_shared_venv_step(args, console)
    return result
