"""wiki_scope_detect: resolve active-project scope via proj.yaml presence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_PROJ_YAML_PATH = Path.home() / ".claude" / "proj.yaml"


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_scope_detect)


def wiki_scope_detect() -> str:
    """Detect active project scope via proj.yaml introspection.

    Returns JSON {scope, proj_present}:
        - scope: "project:<name>" if proj loaded + active project set, else "global"
        - proj_present: whether proj.yaml exists on disk

    NOTE: Active project is session-scoped only (stored in proj server memory,
    not persisted to proj.yaml). Therefore, this tool always returns scope="global"
    when reading proj.yaml directly. The scope concept is reserved for future use
    when proj implements persistent active-project tracking.
    """
    proj_present = _PROJ_YAML_PATH.exists()
    if not proj_present:
        return json.dumps({"scope": "global", "proj_present": False})

    try:
        with _PROJ_YAML_PATH.open() as f:
            yaml.safe_load(f)  # type: ignore[misc]
    except yaml.YAMLError:
        # Malformed YAML: file exists but cannot be parsed.
        return json.dumps({"scope": "global", "proj_present": True})

    # Active project is session-scoped only, not persisted to proj.yaml.
    # Always return global scope. Reserved for future active-project persistence.
    return json.dumps({"scope": "global", "proj_present": True})
