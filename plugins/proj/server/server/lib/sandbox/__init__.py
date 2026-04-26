"""Back-compat shim — sandbox lib lives in plugins/_shared/sandbox/.

Exists so existing in-tree imports like `from server.lib.sandbox.storage
import mcp_allow_entry` keep working without churn during the migration.
New code should import directly from `sandbox`.
"""

from __future__ import annotations

from sandbox import storage
from sandbox.models import (
    Permissions,
    SandboxConfig,
    SandboxFilesystem,
    SandboxNetwork,
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
    "SandboxConfig",
    "SandboxFilesystem",
    "SandboxNetwork",
    "SettingsFile",
    "allow_entries_for_path",
    "mcp_allow_entry",
    "skill_allow_entry",
    "storage",
]
