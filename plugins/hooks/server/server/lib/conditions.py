"""Config-driven condition evaluation for hooks.

Loads ``~/.claude/proj.yaml`` at fire time and resolves dot-path conditions
(e.g. ``sync.todoist.enabled``, ``perms_integration``) to gate whether a hook
should fire.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJ_CONFIG_PATH = Path.home() / ".claude" / "proj.yaml"


def _load_proj_config(path: Path | None = None) -> dict[str, Any]:
    """Load ``~/.claude/proj.yaml`` as a raw dict.

    Returns an empty dict when the file is missing or unparseable — condition
    evaluation treats missing keys as ``False`` so callers never see an error.
    """
    target = path or _PROJ_CONFIG_PATH
    if not target.exists():
        return {}
    try:
        with target.open() as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            return raw
    except Exception:  # noqa: BLE001
        logger.debug("Could not read %s for condition evaluation", target)
    return {}


def _walk_dot_path(obj: Any, path: str) -> Any:
    """Walk a dotted key path into *obj*.

    Supports nested dict keys and integer list indices.  Returns ``None``
    when any segment is missing — callers interpret that as falsy.
    """
    current: Any = obj
    for segment in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, list):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def evaluate_condition(
    condition: str | None,
    *,
    config_path: Path | None = None,
) -> bool:
    """Return ``True`` when the hook should fire based on proj config.

    Rules:
    * ``None`` or empty string — always fires (no condition).
    * A leading ``!`` inverts the result.
    * The dot-path is resolved against the live ``~/.claude/proj.yaml``.
    * Missing config / missing key / unparseable file — treated as ``False``
      (hook is silently skipped, never an error).
    """
    if not condition:
        return True

    negate = False
    expr = condition.strip()
    if expr.startswith("!"):
        negate = True
        expr = expr[1:].strip()

    config = _load_proj_config(config_path)
    val = _walk_dot_path(config, expr)
    result = bool(val)
    return (not result) if negate else result


def resolve_condition_status(
    condition: str | None,
    *,
    config_path: Path | None = None,
) -> str:
    """Human-readable status string for ``hooks_list`` display.

    Returns one of:
    * ``"always"``       — no condition set
    * ``"active"``       — condition evaluates to True right now
    * ``"inactive"``     — condition evaluates to False right now
    """
    if not condition:
        return "always"
    return "active" if evaluate_condition(condition, config_path=config_path) else "inactive"
