"""Managed CLAUDE.md section: CRUD + canonical content.

Originally lived under `installer/claudemd.py`. Moved to `_shared` so both the
installer CLI and the proj MCP server can import the logic + content file
without the proj server picking up a reverse dependency on the installer.
"""

from claudemd.claudemd import (
    MANAGED_SECTION,
    MARKER_END,
    MARKER_START,
    ensure_managed_section,
    has_managed_section,
    remove_managed_section,
)

__all__ = [
    "MANAGED_SECTION",
    "MARKER_END",
    "MARKER_START",
    "ensure_managed_section",
    "has_managed_section",
    "remove_managed_section",
]
