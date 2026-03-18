"""Trello configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TrelloConfig:
    """Trello API configuration."""

    api_key: str
    token: str
    default_board_id: str = ""
    rate_limit_per_10s: int = 100
    allowed_board_ids: list[str] = field(default_factory=list)


_cached_config: TrelloConfig | None = None


def load_config() -> TrelloConfig:
    """Load Trello configuration from YAML file or environment variables.

    Resolution order:
    1. TRELLO_CONFIG env var points to a YAML file -> parse it
    2. Default ~/.claude/trello.yaml if it exists -> parse it
    3. TRELLO_API_KEY and TRELLO_TOKEN env vars
    4. Raise an error with setup instructions
    """
    global _cached_config  # noqa: PLW0603
    if _cached_config is not None:
        return _cached_config

    config_path = Path(os.environ.get("TRELLO_CONFIG", "~/.claude/trello.yaml")).expanduser()

    if config_path.exists():
        with config_path.open() as f:
            data = yaml.safe_load(f) or {}
        _cached_config = TrelloConfig(
            api_key=data.get("api_key", ""),
            token=data.get("token", ""),
            default_board_id=data.get("default_board_id", ""),
            rate_limit_per_10s=data.get("rate_limit_per_10s", 100),
            allowed_board_ids=data.get("allowed_board_ids", []),
        )
        if not _cached_config.api_key or not _cached_config.token:
            msg = f"Trello YAML config at {config_path} is missing api_key or token."
            raise ValueError(msg)
        return _cached_config

    api_key = os.environ.get("TRELLO_API_KEY", "")
    token = os.environ.get("TRELLO_TOKEN", "")
    if api_key and token:
        _cached_config = TrelloConfig(api_key=api_key, token=token)
        return _cached_config

    msg = (
        "Trello config not found. "
        "Create ~/.claude/trello.yaml or set TRELLO_API_KEY/TRELLO_TOKEN env vars."
    )
    raise ValueError(msg)
