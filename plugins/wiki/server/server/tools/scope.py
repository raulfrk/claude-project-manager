"""wiki_scope_detect: resolve active-project scope via proj plugin state.

Reads two files, both owned by proj plugin:
  - ~/.claude/proj.yaml          (existence signal → proj_present)
  - ~/.claude/proj-session.yaml  (active project name → scope)

No cross-MCP calls; pure file I/O per spec §3 persistence/synthesis boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_PROJ_YAML_PATH = Path.home() / ".claude" / "proj.yaml"
_SESSION_YAML_PATH = Path.home() / ".claude" / "proj-session.yaml"


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_scope_detect)


def _read_active_from_session() -> str | None:
    """Read proj-session.yaml's `active` field. None if missing/malformed/empty."""
    if not _SESSION_YAML_PATH.exists():
        return None
    try:
        with _SESSION_YAML_PATH.open() as f:
            data = yaml.safe_load(f)  # type: ignore[misc]
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("active")  # type: ignore[attr-defined]
    if not value:
        return None
    return str(value)  # type: ignore[arg-type]


def _proj_yaml_present() -> bool:
    """True if ~/.claude/proj.yaml exists (regardless of contents)."""
    return _PROJ_YAML_PATH.exists()


def wiki_scope_detect() -> str:
    """Detect active project scope via proj plugin's session file.

    Returns JSON {scope, proj_present}:
        - scope: "project:<name>" if proj_session_yaml has active project, else "global"
        - proj_present: whether ~/.claude/proj.yaml exists on disk
    """
    proj_present = _proj_yaml_present()
    active = _read_active_from_session()
    scope = f"project:{active}" if active else "global"
    return json.dumps({"scope": scope, "proj_present": proj_present})
