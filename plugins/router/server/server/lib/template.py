"""Resolve ${} template expressions against a source_result dict."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.lib._types import JsonValue

_log = logging.getLogger(__name__)

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
            _log.warning("Template variable ${%s} not found in source", match.group(1))
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

    Dict values of the shape ``{"value": ..., "omit_if_empty": True}`` are
    resolved specially: when the resolved value is falsy (None, "", 0, [], {}),
    the key is omitted from the output dict. All other values resolve normally.
    """
    out: dict[str, JsonValue] = {}
    for key, value in param_mapping.items():
        if _is_omit_if_empty_directive(value):
            directive: dict[str, JsonValue] = value  # type: ignore[assignment]
            resolved = resolve_value(directive["value"], source)
            if _is_empty(resolved):
                continue
            out[key] = resolved
        elif _is_value_directive(value):
            directive = value  # type: ignore[assignment]
            out[key] = resolve_value(directive["value"], source)
        else:
            out[key] = resolve_value(value, source)
    return out


def _is_value_directive(value: JsonValue) -> bool:
    """Return True if *value* has both ``value`` + ``omit_if_empty`` keys.

    Used by `resolve_mapping` to spot the `omit_if_empty: False` explicit-opt-out
    case, where the directive form is preserved but the key is kept even when
    the resolved value is falsy. Distinct from `_is_omit_if_empty_directive`,
    which is stricter and only matches `omit_if_empty: True`.
    """
    return isinstance(value, dict) and "value" in value and "omit_if_empty" in value


def _is_omit_if_empty_directive(value: JsonValue) -> bool:
    return isinstance(value, dict) and "value" in value and value.get("omit_if_empty") is True


def _is_empty(value: JsonValue) -> bool:
    if value is None:
        return True
    # bool must precede int check — bool is a subclass of int in Python.
    # True/False are never "empty" (they are valid values, not absence of value).
    if isinstance(value, bool):
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) == 0
    if isinstance(value, (int, float)):
        return value == 0
    return False
