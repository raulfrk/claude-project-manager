"""YAML-frontmatter + markdown-body parser."""

from __future__ import annotations

from typing import Any, cast

import yaml


class FrontmatterError(ValueError):
    """Raised when a markdown string has malformed frontmatter."""


_DELIM = "---"


def parse(raw: str) -> tuple[dict[str, Any], str]:
    """Parse a markdown string with optional YAML frontmatter.

    Returns (frontmatter_dict, body_str). Frontmatter is {} if absent.
    Raises FrontmatterError on malformed frontmatter.
    """
    if not raw.startswith(_DELIM + "\n") and raw != _DELIM:
        return {}, raw

    # Find closing delimiter on its own line.
    lines = raw.split("\n")
    closing_idx = -1
    for i in range(1, len(lines)):
        if lines[i] == _DELIM:
            closing_idx = i
            break
    if closing_idx == -1:
        raise FrontmatterError("unterminated frontmatter: missing closing '---'")

    fm_text = "\n".join(lines[1:closing_idx])
    try:
        loaded = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        raise FrontmatterError(f"invalid YAML in frontmatter: {e}") from e

    fm = cast("dict[str, Any]", loaded or {})
    if not isinstance(fm, dict):  # type: ignore[unreachable]
        raise FrontmatterError(f"frontmatter must be a YAML mapping, got {type(fm).__name__}")

    body = "\n".join(lines[closing_idx + 1 :])
    return fm, body


def dump(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body back into a markdown string.

    Empty frontmatter → body only (no delimiters).
    """
    if not frontmatter:
        return body
    fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"{_DELIM}\n{fm_yaml}\n{_DELIM}\n{body}"
