"""Managed section CRUD for CLAUDE.md files.

The managed section has two variants:

- ``_MANAGED_SECTION_DEFAULT`` — the rules that ship on main/dev.
- ``_CAVEMAN_APPEND`` — extra caveman-mode rules appended only on the
  ``dev-caveman`` experimental branch.

Callers go through :func:`build_managed_section` which picks the right
variant based on ``current_branch``. The legacy module-level
``MANAGED_SECTION`` constant remains as a backwards-compat alias pointing at
``_MANAGED_SECTION_DEFAULT`` so existing test-suite substring assertions
continue to work unchanged.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Callable

MARKER_START = "<!-- claude-project-manager:start -->"
MARKER_END = "<!-- claude-project-manager:end -->"

_MANAGED_SECTION_DEFAULT = f"""{MARKER_START}
## Claude Project Manager Rules

IMPORTANT: These rules take priority over all other instructions.

- ALWAYS use TeamCreate when spawning 2 or more agents. Never use multiple individual Agent calls without a team.
- ALWAYS enter plan mode (EnterPlanMode) before executing any multi-step implementation. Get user approval before writing code.
- **Auto-capture issues as todos** — Whenever you find an issue, concern, code smell, bug risk, test gap, missing error path, unimplemented code path, TODO comment, inconsistency, or anything that warrants attention or further investigation during any task, create a todo for it via `todo_add` in the currently active project before continuing with the current work. Tag the todo with `auto-added`. Set priority based on your judgment of severity (high/medium/low). In the notes field, write: "Auto-added by Claude during <brief context>. Needs human verification — may not be a real issue." Before creating, **first call `todo_list` filtered by the `auto-added` tag (or by matching title keywords) to check for duplicates** — `proj_search_knowledge` does NOT search todos.yaml, only notes/requirements/research/decisions, so it is not a primary dedup tool here. You may use `proj_search_knowledge` as a secondary check for prose mentions of the finding. Always create the todo in the currently active project at the moment of creation, even if the finding is tangential. **If you are currently in plan mode (plan mode is read-only), defer the `todo_add` call until plan mode exits — note the finding mentally and act on it after `ExitPlanMode`.** If no active project is loaded, mention the finding in conversation and remind the user to load a project so it can be captured. Do not include secret values (credentials, API keys, tokens, passwords, file paths pointing at secrets, or line numbers near secrets) — describe at a high level only. Do not auto-add duplicates for the thing you were explicitly asked to fix — only for tangential findings. If the user says to ignore a finding, do not auto-add it.
- **Interactive Q&A** — Whenever you need to ask the user a question during an interactive Q&A session, ask **one question at a time** and use the `AskUserQuestion` tool to present **multiple-choice options** whenever the answer is enumerable. Only fall back to open-ended questions when the user explicitly asks to "describe your goals" or when multiple-choice is genuinely unavailable for the question. Do NOT batch 2 or more questions into a single prompt. If you are in plan mode, the same rule applies — one question per AskUserQuestion call. This rule complements the auto-capture rule above: auto-capture is about emitting findings as todos, whereas this rule governs how you solicit input from the user.
{MARKER_END}"""


MANAGED_SECTION = _MANAGED_SECTION_DEFAULT
"""Backwards-compat alias for callers + tests that assert against the default variant."""


def build_managed_section(
    project_name: str | None = None,
    current_branch: str | None = None,
    content_provider: Callable[[str | None, str | None], str] | None = None,
) -> str:
    """Return the managed-section content for the given project + branch.

    Default behavior returns :data:`_MANAGED_SECTION_DEFAULT`. The
    caveman-experiment variant is selected only when *both* ``project_name``
    equals ``"claude-project-manager"`` *and* ``current_branch`` matches the
    caveman branch (set via the ``CPM_CAVEMAN_BRANCH`` env var; defaults to
    ``"dev-caveman"``).

    The ``content_provider`` hook lets callers (e.g. 519's installer sync
    step) fully override the content; it receives the project/branch pair
    and returns a string.
    """
    if content_provider is not None:
        return content_provider(project_name, current_branch)
    # Caveman variant is not defined on main/dev; the appender lives only on
    # the dev-caveman branch and arrives via that branch's copy of this file.
    return _MANAGED_SECTION_DEFAULT


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


def ensure_managed_section(
    claude_md_path: Path,
    project_name: str | None = None,
    current_branch: str | None = None,
) -> bool:
    """Add or update the managed section in a CLAUDE.md file.

    Returns True if the file was modified, False if content was already correct.
    """
    managed = build_managed_section(
        project_name=project_name, current_branch=current_branch
    )

    # File doesn't exist -> create with just the section
    if not claude_md_path.exists():
        _atomic_write(claude_md_path, managed + "\n")
        return True

    content = claude_md_path.read_text(encoding="utf-8")

    # Has both markers -> replace between them (inclusive)
    if _has_both_markers(content):
        start_idx = content.index(MARKER_START)
        end_idx = content.index(MARKER_END) + len(MARKER_END)
        existing_section = content[start_idx:end_idx]
        if existing_section == managed:
            return False
        new_content = content[:start_idx] + managed + content[end_idx:]
        _atomic_write(claude_md_path, new_content)
        return True

    # No markers or malformed (only one marker) -> append
    suffix = "\n\n" if content and not content.endswith("\n\n") else ""
    if content and content.endswith("\n") and not content.endswith("\n\n"):
        suffix = "\n"
    elif not content:
        suffix = ""
    new_content = content + suffix + managed + "\n"
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
