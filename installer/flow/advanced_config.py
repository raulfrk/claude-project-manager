"""prompt_toolkit replacement for Textual AdvancedConfigScreen.

Iterates PROJ_YAML_PROMPTS with tier="advanced", builds FieldSpec list
with defaults from existing yaml, calls run_form.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.flow.form import FieldSpec, run_form
from installer.wizard_specs import PROJ_YAML_PROMPTS, get_distinct_yaml_files


def _spec_to_field_kind(spec_type: str, sensitive: bool) -> str:
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


def run_advanced_config(console: Console) -> dict[str, Any] | None:
    claude_home = Path.home() / ".claude"

    buckets: dict[str, dict[str, Any]] = {}
    for bucket_name in get_distinct_yaml_files(PROJ_YAML_PROMPTS):
        buckets[bucket_name] = _load_bucket(bucket_name, claude_home)

    proj_bucket = buckets.get("proj", {})
    fields: list[FieldSpec] = []

    for spec in PROJ_YAML_PROMPTS:
        if spec.tier != "advanced":
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

    return run_form(fields, console, title="Advanced Configuration")
