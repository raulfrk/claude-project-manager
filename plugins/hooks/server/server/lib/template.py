"""Resolve ${} template expressions against a source_result dict."""

from __future__ import annotations

import json
import re
from typing import Any

_TEMPLATE_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_path(obj: Any, path: str) -> Any:
    """Walk a dotted path (e.g. 'result.path' or 'result.items.0.name') into *obj*.

    Supports dict keys and integer list indices.  Returns ``None`` when a segment
    is missing rather than raising.
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


def resolve_template(template: str, source: dict[str, Any]) -> str:
    """Replace every ``${...}`` placeholder in *template* with the value looked up in *source*.

    If the **entire** template is a single ``${path}`` and the resolved value is
    not a string, the JSON representation is returned so that objects/arrays are
    preserved.  When the template contains literal text around the placeholder the
    resolved value is stringified.
    """
    # Fast path: whole string is one placeholder
    m = _TEMPLATE_RE.fullmatch(template)
    if m is not None:
        val = _resolve_path(source, m.group(1))
        if val is None:
            return ""
        if isinstance(val, str):
            return val
        return json.dumps(val)

    def _replacer(match: re.Match[str]) -> str:
        val = _resolve_path(source, match.group(1))
        if val is None:
            return ""
        if isinstance(val, str):
            return val
        return json.dumps(val)

    return _TEMPLATE_RE.sub(_replacer, template)


def resolve_mapping(
    param_mapping: dict[str, str],
    source: dict[str, Any],
) -> dict[str, Any]:
    """Resolve every value in *param_mapping* against *source*.

    Returns a new dict with the same keys and resolved string values.
    """
    resolved: dict[str, Any] = {}
    for key, tmpl in param_mapping.items():
        resolved[key] = resolve_template(tmpl, source)
    return resolved
