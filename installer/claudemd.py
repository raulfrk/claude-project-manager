"""Managed section CRUD for CLAUDE.md files."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

MARKER_START = "<!-- claude-project-manager:start -->"
MARKER_END = "<!-- claude-project-manager:end -->"

_SECTION_PATH = Path(__file__).parent / "managed_section.md"
MANAGED_SECTION = _SECTION_PATH.read_text(encoding="utf-8").rstrip("\n")
assert MANAGED_SECTION.startswith(MARKER_START), (
    "managed_section.md first line must match MARKER_START"
)
assert MANAGED_SECTION.endswith(MARKER_END), (
    "managed_section.md last line must match MARKER_END"
)


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


def _has_both_markers(content: str) -> bool:
    """Return True if content contains both start and end markers."""
    return MARKER_START in content and MARKER_END in content


def ensure_managed_section(claude_md_path: Path) -> bool:
    """Add or update the managed section in a CLAUDE.md file.

    Returns True if the file was modified, False if content was already correct.
    """
    # File doesn't exist -> create with just the section
    if not claude_md_path.exists():
        _atomic_write(claude_md_path, MANAGED_SECTION + "\n")
        return True

    content = claude_md_path.read_text(encoding="utf-8")

    # Has both markers -> replace between them (inclusive)
    if _has_both_markers(content):
        start_idx = content.index(MARKER_START)
        end_idx = content.index(MARKER_END) + len(MARKER_END)
        existing_section = content[start_idx:end_idx]
        if existing_section == MANAGED_SECTION:
            return False
        new_content = content[:start_idx] + MANAGED_SECTION + content[end_idx:]
        _atomic_write(claude_md_path, new_content)
        return True

    # No markers or malformed (only one marker) -> append
    suffix = "\n\n" if content and not content.endswith("\n\n") else ""
    if content and content.endswith("\n") and not content.endswith("\n\n"):
        suffix = "\n"
    elif not content:
        suffix = ""
    new_content = content + suffix + MANAGED_SECTION + "\n"
    _atomic_write(claude_md_path, new_content)
    return True


def remove_managed_section(claude_md_path: Path) -> bool:
    """Remove the managed section from a CLAUDE.md file.

    Returns True if the file was modified, False if no markers were found.
    """
    if not claude_md_path.exists():
        return False

    content = claude_md_path.read_text(encoding="utf-8")

    if not _has_both_markers(content):
        return False

    start_idx = content.index(MARKER_START)
    end_idx = content.index(MARKER_END) + len(MARKER_END)

    # Remove the section and trailing newlines
    before = content[:start_idx]
    after = content[end_idx:].lstrip("\n")

    new_content = before.rstrip("\n")
    if new_content and after:
        new_content += "\n\n" + after
    elif after:
        new_content = after
    elif new_content:
        new_content += "\n"

    _atomic_write(claude_md_path, new_content)
    return True


def has_managed_section(claude_md_path: Path) -> bool:
    """Check if the managed section exists in a CLAUDE.md file."""
    if not claude_md_path.exists():
        return False
    try:
        content = claude_md_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return MARKER_START in content
