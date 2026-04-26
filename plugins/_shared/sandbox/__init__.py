"""Sandbox library shared between installer and proj plugin.

Pure-Python lib for reading/writing ~/.claude/settings.json. Owns the
allow-rule semantics for MCP servers, sandbox paths, and skill prefixes.
The proj plugin's tools/sandbox.py wraps these primitives in MCP tools;
the installer calls reconcile_settings directly during install finalize.
"""

from __future__ import annotations

from sandbox import storage
from sandbox.models import (
    Permissions,
    SandboxFilesystem,
    SettingsFile,
)
from sandbox.storage import (
    SETTINGS_PATH,
    allow_entries_for_path,
    mcp_allow_entry,
    skill_allow_entry,
)

__all__ = [
    "SETTINGS_PATH",
    "Permissions",
    "SandboxFilesystem",
    "SettingsFile",
    "allow_entries_for_path",
    "mcp_allow_entry",
    "skill_allow_entry",
    "storage",
]
