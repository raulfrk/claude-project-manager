"""Shared helpers for loading existing YAML config during installer wizard.

Both the Rich CLI path (installer/wizard.py) and the Textual TUI path
(installer/screens/*.py) use this module to read ~/.claude/proj.yaml,
~/.claude/worktree.yaml, ~/.claude/todoist.yaml, ~/.claude/trello.yaml,
and ~/.claude/jira.yaml and surface existing values as wizard defaults.

Contract:
- load_existing_yaml(path) returns {} on missing or empty files, raises
  ConfigLoadError on any yaml parse error.
- get_nested(d, dotted_key, default) walks a nested dict by dotted path;
  returns default if any segment is missing, None, or wrong type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigLoadError(Exception):
    """Raised when an existing yaml config file cannot be parsed."""

    def __init__(self, path: Path, original: Exception) -> None:
        super().__init__(f"Failed to load {path}: {original}")
        self.path = path
        self.original = original


def load_existing_yaml(path: Path) -> dict[str, Any]:
    """Return the parsed yaml dict at path, or {} if missing/empty.

    Raises ConfigLoadError on parse errors. A file that contains only
    whitespace, a null document, or a non-dict top-level value is treated
    as empty and returns {}.
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigLoadError(path, exc) from exc
    if not raw.strip():
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(path, exc) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def get_nested(d: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Walk dict d by dotted_key, returning default on any miss.

    Returns default if:
    - any intermediate segment is missing
    - any intermediate value is None or not a dict
    - the final value is None

    Never raises; always returns either the found value or the default.
    """
    if not dotted_key:
        return default
    current: Any = d
    for segment in dotted_key.split("."):
        if not isinstance(current, dict):
            return default
        if segment not in current:
            return default
        current = current[segment]
        if current is None:
            return default
    return current
