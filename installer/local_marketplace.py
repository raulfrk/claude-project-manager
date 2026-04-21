"""Local marketplace clone management for the installer.

Clones the claude-project-manager marketplace repo into a fixed cache
directory so the installer can register a local path as the Claude Code
marketplace source (used by --local-marketplace).
"""

from __future__ import annotations

from pathlib import Path

LOCAL_CLONE_DIR = (
    Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"
)
_HTTPS_SOURCE = "https://github.com/raulfrk/claude-project-manager.git"
_GIT_TIMEOUT = 120  # seconds
