"""Back-compat shim — sandbox models live in plugins/_shared/sandbox/models.py.

Existing in-tree imports like `from server.lib.sandbox.models import SettingsFile`
keep working without churn during the migration. New code should import directly
from `sandbox.models`.
"""

from __future__ import annotations

from sandbox.models import (
    Permissions,
    SandboxConfig,
    SandboxFilesystem,
    SandboxNetwork,
    SettingsFile,
)

__all__ = [
    "Permissions",
    "SandboxConfig",
    "SandboxFilesystem",
    "SandboxNetwork",
    "SettingsFile",
]
