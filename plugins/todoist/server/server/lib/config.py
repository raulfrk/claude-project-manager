"""Todoist configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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

    api_token = data.get("api_token", "")
    if not api_token or not str(api_token).strip():
        msg = f"Todoist config at {config_path} is missing api_token."
        raise ValueError(msg)

    _cached_config = TodoistConfig(
        api_token=str(api_token).strip(),
        enabled=data.get("enabled", True),
        auto_sync=data.get("auto_sync", True),
        root_only=data.get("root_only", False),
    )
    return _cached_config
