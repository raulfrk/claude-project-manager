"""wiki_scope_detect: resolve active-project scope via proj plugin state.

Reads two files, both owned by proj plugin:
  - ~/.claude/proj.yaml          (existence signal → proj_present)
  - ~/.claude/proj-session.yaml  (pid-keyed v2 schema; active project for this session)

No cross-MCP calls; pure file I/O per spec §3 persistence/synthesis boundary.
The pid-key logic lives in the shared `session_key` helper (see plugins/_shared/session_key/).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import anyio.to_thread
import session_key

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_PROJ_YAML_PATH = Path.home() / ".claude" / "proj.yaml"
_SESSION_YAML_PATH = Path.home() / ".claude" / "proj-session.yaml"
_session_key_fn = session_key.get_claude_session_key


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_scope_detect)


def _read_active_from_session() -> str | None:
    """Read active project for the current session from v2 proj-session.yaml."""
    return session_key.read_active(_SESSION_YAML_PATH, session_key=_session_key_fn())


def _proj_yaml_present() -> bool:
    """True if ~/.claude/proj.yaml exists (regardless of contents)."""
    return _PROJ_YAML_PATH.exists()


async def wiki_scope_detect() -> str:
    """Detect active project scope via proj plugin's session file.

    Returns JSON {scope, proj_present}:
        - scope: "project:<name>" if this session has an active project, else "global"
        - proj_present: whether ~/.claude/proj.yaml exists on disk
    """

    def _do_detect() -> dict[str, Any]:
        proj_present = _proj_yaml_present()
        active = _read_active_from_session()
        scope = f"project:{active}" if active else "global"
        return {"scope": scope, "proj_present": proj_present}

    return json.dumps(await anyio.to_thread.run_sync(_do_detect))
