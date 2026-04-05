"""Resolve ${} template expressions against a source_result dict."""

from __future__ import annotations

import json
import re

from server.lib._types import JsonValue

_TEMPLATE_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_path(obj: JsonValue, path: str) -> JsonValue:
    """Walk a dotted path (e.g. 'result.path' or 'result.items.0.name') into *obj*.

    Supports dict keys and integer list indices.  Returns ``None`` when a segment
    is missing rather than raising.
    """
    current: JsonValue = obj
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


def resolve_template(template: str, source: dict[str, JsonValue]) -> JsonValue:
    """Replace every ``${...}`` placeholder in *template* with the value looked up in *source*.

    If the **entire** template is a single ``${path}`` and the resolved value is
    not a string, the native Python value is returned so that objects/arrays/ints
    are preserved.  When the template contains literal text around the placeholder
    the resolved value is stringified.
    """
    # Fast path: whole string is one placeholder
    m = _TEMPLATE_RE.fullmatch(template)
    if m is not None:
        val = _resolve_path(source, m.group(1))
        return val

    def _replacer(match: re.Match[str]) -> str:
        val = _resolve_path(source, match.group(1))
        if val is None:
            return ""
        if isinstance(val, str):
            return val
        return json.dumps(val)

    return _TEMPLATE_RE.sub(_replacer, template)


def resolve_value(value: JsonValue, context: dict[str, JsonValue]) -> JsonValue:
    """Resolve a value that may be a string template, nested dict, or list."""
    if isinstance(value, str):
        return resolve_template(value, context)
    elif isinstance(value, dict):
        return {k: resolve_value(v, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    else:
        # int, bool, None, float — pass through unchanged
        return value


def resolve_mapping(
    param_mapping: dict[str, JsonValue],
    source: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Resolve every value in *param_mapping* against *source*.

    Returns a new dict with the same keys and resolved values.
    """
    return {key: resolve_value(value, source) for key, value in param_mapping.items()}
