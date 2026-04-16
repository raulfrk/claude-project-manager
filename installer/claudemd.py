"""Backwards-compatible re-exports from the ``claudemd`` shared package.

The canonical home for the managed CLAUDE.md section logic and content is
``plugins/_shared/claudemd/`` (packaged as ``claudemd`` under the
``claude-hook-transport`` distribution). This module exists so that existing
import sites inside the installer package (``from installer.claudemd import
ensure_managed_section``) keep working unchanged after the move.

New code should import from ``claudemd`` directly.
"""

from claudemd.claudemd import (  # noqa: F401
    MANAGED_SECTION,
    MARKER_END,
    MARKER_START,
    ensure_managed_section,
    has_managed_section,
    remove_managed_section,
)
