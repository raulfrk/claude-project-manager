"""Wiki runtime config loader (~/.claude/wiki.yaml)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import yaml

from server.lib.models import WikiConfig

_DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "wiki.yaml"


def config_path() -> Path:
    """Resolve wiki config path.

    Reads WIKI_CONFIG env var if set (supports ~-expansion); falls back to
    _DEFAULT_CONFIG_PATH otherwise. Matches the proj plugin's PROJ_CONFIG pattern.
    """
    env_override = os.environ.get("WIKI_CONFIG", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return _DEFAULT_CONFIG_PATH


def config_exists() -> bool:
    return config_path().exists()


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open() as f:
            data: Any = yaml.safe_load(f)
            return cast("dict[str, Any]", data) if isinstance(data, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


def load_config() -> WikiConfig:
    """Load wiki runtime config. Returns defaults if file missing or malformed."""
    data = _load_yaml(config_path())
    return WikiConfig.from_dict(data)


def save_config(cfg: WikiConfig) -> None:
    """Persist wiki runtime config. Creates parent dirs as needed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(cfg.to_dict(), f, sort_keys=False)
