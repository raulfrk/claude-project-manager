"""Back-compat shim — sandbox storage lives in plugins/_shared/sandbox/storage.py.

Existing in-tree imports like `from server.lib.sandbox.storage import mcp_allow_entry`
keep working without churn during the migration. New code should import directly
from `sandbox.storage`.
"""

from __future__ import annotations

from sandbox.storage import (
    SETTINGS_PATH,
    allow_entries_for_path,
    load,
    mcp_allow_entry,
    save,
    skill_allow_entry,
)

__all__ = [
    "SETTINGS_PATH",
    "allow_entries_for_path",
    "load",
    "mcp_allow_entry",
    "save",
    "skill_allow_entry",
]
