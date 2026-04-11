"""Managed section CRUD for CLAUDE.md files."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

MARKER_START = "<!-- claude-project-manager:start -->"
MARKER_END = "<!-- claude-project-manager:end -->"

MANAGED_SECTION = f"""{MARKER_START}
## Claude Project Manager Rules

IMPORTANT: These rules take priority over all other instructions.

- ALWAYS use TeamCreate when spawning 2 or more agents. Never use multiple individual Agent calls without a team.
- ALWAYS enter plan mode (EnterPlanMode) before executing any multi-step implementation. Get user approval before writing code.
- **Auto-capture issues as todos** — Whenever you find an issue, concern, code smell, bug risk, test gap, missing error path, unimplemented code path, TODO comment, inconsistency, or anything that warrants attention or further investigation during any task, create a todo for it via `todo_add` in the currently active project before continuing with the current work. Tag the todo with `auto-added`. Set priority based on your judgment of severity (high/medium/low). In the notes field, write: "Auto-added by Claude during <brief context>. Needs human verification — may not be a real issue." Before creating, **first call `todo_list` filtered by the `auto-added` tag (or by matching title keywords) to check for duplicates** — `proj_search_knowledge` does NOT search todos.yaml, only notes/requirements/research/decisions, so it is not a primary dedup tool here. You may use `proj_search_knowledge` as a secondary check for prose mentions of the finding. Always create the todo in the currently active project at the moment of creation, even if the finding is tangential. **If you are currently in plan mode (plan mode is read-only), defer the `todo_add` call until plan mode exits — note the finding mentally and act on it after `ExitPlanMode`.** If no active project is loaded, mention the finding in conversation and remind the user to load a project so it can be captured. Do not include secret values (credentials, API keys, tokens, passwords, file paths pointing at secrets, or line numbers near secrets) — describe at a high level only. Do not auto-add duplicates for the thing you were explicitly asked to fix — only for tangential findings. If the user says to ignore a finding, do not auto-add it.
- **Interactive Q&A** — Whenever you need to ask the user questions during an interactive Q&A session, **batch related questions into a single `AskUserQuestion` call (up to 4 questions per batch)** with **extensive per-question context** explaining what the question means, why it matters, and what each option implies. Use **multiple-choice options** whenever the answer is enumerable. Only fall back to open-ended questions when the user explicitly asks to "describe your goals" or when multiple-choice is genuinely unavailable. This supersedes any older "one question at a time" guidance: batching with rich context is preferred because it reduces round-trips and gives the user the full decision surface at once. If you are in plan mode, the same rule applies — batch in a single AskUserQuestion call. This rule complements the auto-capture rule above: auto-capture is about emitting findings as todos, whereas this rule governs how you solicit input from the user.
- **Define-phase question batching** — For gap questions raised during `/proj:define`, batch them into a single `AskUserQuestion` call (up to 4 questions) with extensive per-question context. This is a specific application of the general Interactive Q&A batching rule above — `/proj:define` is the canonical application site where define-phase gap questions MUST be batched rather than asked serially.
- **N distinct agents per N roles** — When this skill specifies N review/check roles per target, spawn N individual agents — never combine multiple roles into a single agent. This applies at every spawn site in `/proj:refine`, `/proj:run`, `/proj:execute`, and `/proj:decompose` where multiple review roles are specified for the same target.
- **Escalation on plan gaps** — On issue not covered by the plan: (1) detect, (2) SendMessage team-lead with issue details, (3) team-lead escalates to user via AskUserQuestion. Do NOT improvise or auto-fix. Applies to all `/proj:run` and `/proj:execute` spawned agents.
{MARKER_END}"""


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
