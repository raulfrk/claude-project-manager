"""Todoist configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml


@dataclass
class TodoistConfig:
    """Todoist API configuration."""

    api_token: str
    enabled: bool = True
    auto_sync: bool = True
    root_only: bool = False


_cached_config: TodoistConfig | None = None


def load_config() -> TodoistConfig:
    """Load Todoist configuration from YAML file.

    Resolution order:
    1. TODOIST_CONFIG env var points to a YAML file -> parse it
    2. Default ~/.claude/todoist.yaml
    """
    global _cached_config  # noqa: PLW0603
    if _cached_config is not None:
        return _cached_config

    config_path = Path(
        os.environ.get("TODOIST_CONFIG", "~/.claude/todoist.yaml")
    ).expanduser()

    if not config_path.exists():
        msg = (
            "Todoist not configured. "
            "Create ~/.claude/todoist.yaml with api_token field."
        )
        raise ValueError(msg)

    try:
        with config_path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in {config_path}: {exc}"
        raise ValueError(msg) from None

    if not isinstance(data, dict):
        msg = f"Invalid YAML in {config_path}: expected a mapping, got {type(data).__name__}"
        raise ValueError(msg)

    # yaml.safe_load returns an untyped value; after isinstance check we know it's a dict
    config_data = cast("dict[str, str | bool]", data)

    api_token = str(config_data.get("api_token", ""))
    if not api_token.strip():
        msg = f"Todoist config at {config_path} is missing api_token."
        raise ValueError(msg)

    _cached_config = TodoistConfig(
        api_token=api_token.strip(),
        enabled=bool(config_data.get("enabled", True)),
        auto_sync=bool(config_data.get("auto_sync", True)),
        root_only=bool(config_data.get("root_only", False)),
    )
    return _cached_config
