"""Backwards-compatible re-exports from the ``claudemd`` shared package.

Historical import sites (e.g. ``from installer.claudemd import ...``) keep
working after the move to ``plugins/_shared/claudemd/``.
"""

from claudemd.claudemd import (  # noqa: F401
    MANAGED_SECTION,
    MARKER_END,
    MARKER_START,
    ensure_managed_section,
    has_managed_section,
    remove_managed_section,
)
