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

Sidecar backup/restore: when the caveman variant is installed, the prior
managed section is preserved in a sidecar file (``~/.claude/CLAUDE.md.pre-caveman``)
with a magic header so a later restore knows what it's reverting from and
can preserve any user edits to non-managed regions.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable

CAVEMAN_BRANCH_GLOB = os.environ.get("CPM_CAVEMAN_BRANCH", "*caveman*")
CAVEMAN_PROJECT_NAME = "claude-project-manager"
CAVEMAN_SIDECAR_SUFFIX = ".pre-caveman"
CAVEMAN_SIDECAR_HEADER_PREFIX = "# CPM-CAVEMAN-BACKUP v1"

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


# cpm:caveman — banned marker on main/dev; intentional on dev-caveman only.
# The CI guard and pre-commit hook reject this string on main/dev.
_CAVEMAN_APPEND = """
## Caveman-Aware Output

Output may be compressed (terse, fragment-style, short synonyms, no filler) when the active project is ``claude-project-manager`` and the current git branch matches ``*caveman*``. Compression is a presentation layer, never a rule override. Preserve verbatim even under compression:

- Security and safety rules (refusals, destructive-op gating, user-confirmation requirements) — always full prose
- Commit messages, code comments, test strings, source error messages — always normal prose
- YAML frontmatter, MCP tool names, file paths, shell commands, code blocks — never abbreviated
- Load-bearing qualifiers in SKILL.md bodies ("ON by default except ``--paranoid``", explicit defaults, "never use ``--no-verify``") — preserved verbatim

If a rewrite would drop a qualifier in any of the above categories, the rewrite is wrong. Revert to full prose for that passage.
"""


def build_managed_section(
    project_name: str | None = None,
    current_branch: str | None = None,
    content_provider: Callable[[str | None, str | None], str] | None = None,
) -> str:
    """Return the managed-section content for the given project + branch.

    Default behavior returns :data:`_MANAGED_SECTION_DEFAULT`. The
    caveman-experiment variant splices :data:`_CAVEMAN_APPEND` in *before*
    the trailing ``MARKER_END`` so the entire caveman block lives inside
    the managed markers and round-trips cleanly through :func:`_split_managed`.
    Variant is selected only when *both* ``project_name`` equals
    ``"claude-project-manager"`` *and* ``current_branch`` matches the
    caveman glob (env var ``CPM_CAVEMAN_BRANCH``; default ``"*caveman*"``).

    The ``content_provider`` hook lets callers fully override the content;
    it receives the project/branch pair and returns a string.
    """
    if content_provider is not None:
        return content_provider(project_name, current_branch)
    if _is_caveman_context(project_name, current_branch):
        # Splice caveman content inside the marker block so split/restore
        # treat it as part of the managed section (not as trailing user text).
        assert _MANAGED_SECTION_DEFAULT.endswith(MARKER_END)
        inner = _MANAGED_SECTION_DEFAULT[: -len(MARKER_END)]
        return inner + _CAVEMAN_APPEND + MARKER_END
    return _MANAGED_SECTION_DEFAULT


def _is_caveman_context(project_name: str | None, current_branch: str | None) -> bool:
    """Return True iff both project and branch qualify for the caveman variant."""
    if project_name != CAVEMAN_PROJECT_NAME:
        return False
    if not current_branch:
        return False
    pattern = re.escape(CAVEMAN_BRANCH_GLOB).replace(r"\*", ".*")
    return re.fullmatch(pattern, current_branch) is not None


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy src to dst atomically via tmp + os.replace."""
    if not src.exists():
        raise FileNotFoundError(f"source does not exist: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(str(src), tmp_path)
        Path(tmp_path).replace(dst)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


def _sidecar_path_for(claude_md_path: Path) -> Path:
    """Compute the sidecar backup path for a given CLAUDE.md path."""
    return claude_md_path.with_name(claude_md_path.name + CAVEMAN_SIDECAR_SUFFIX)


def _sidecar_header_for_now() -> str:
    """Return a fresh sidecar magic-header line (with ISO-8601 UTC timestamp)."""
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return f"{CAVEMAN_SIDECAR_HEADER_PREFIX} {ts}\n"


def _validate_sidecar_header(sidecar_path: Path) -> None:
    """Raise ValueError if sidecar exists but lacks the expected magic header."""
    if not sidecar_path.exists():
        raise FileNotFoundError(f"sidecar not found: {sidecar_path}")
    first_line = ""
    with sidecar_path.open("r", encoding="utf-8") as f:
        first_line = f.readline()
    if not first_line.startswith(CAVEMAN_SIDECAR_HEADER_PREFIX):
        raise ValueError(
            f"sidecar at {sidecar_path} has unexpected header: {first_line!r} "
            f"(expected prefix {CAVEMAN_SIDECAR_HEADER_PREFIX!r})"
        )


def _backup_global_claudemd_for_caveman(
    claude_md_path: Path,
    magic_header: str | None = None,
) -> Path:
    """Copy the current CLAUDE.md to a sidecar backup with a magic header.

    If the sidecar already exists, its first line must match
    :data:`CAVEMAN_SIDECAR_HEADER_PREFIX`; otherwise a ValueError is raised
    so we never clobber something we don't recognize. When the sidecar is
    present and valid we leave it alone — the earliest pre-caveman snapshot
    is what we want to preserve, not the most recent (which would be a
    caveman-state file in a caveman-to-caveman re-run).

    Returns the sidecar path.
    """
    if not claude_md_path.exists():
        raise FileNotFoundError(f"source CLAUDE.md not found: {claude_md_path}")
    sidecar = _sidecar_path_for(claude_md_path)
    if sidecar.exists():
        _validate_sidecar_header(sidecar)
        return sidecar
    header = magic_header or _sidecar_header_for_now()
    source_text = claude_md_path.read_text(encoding="utf-8")
    _atomic_write(sidecar, header + source_text)
    return sidecar


def _split_managed(content: str) -> tuple[str, str, str]:
    """Split content into (before_managed, managed, after_managed).

    If the content has no managed markers, returns (content, "", "").
    The managed block includes the marker lines themselves.
    """
    if not _has_both_markers(content):
        return content, "", ""
    start_idx = content.index(MARKER_START)
    end_idx = content.index(MARKER_END) + len(MARKER_END)
    return content[:start_idx], content[start_idx:end_idx], content[end_idx:]


def _restore_global_claudemd_from_caveman(claude_md_path: Path) -> bool:
    """Restore the default managed section from the sidecar backup.

    Preserves user edits to the non-managed regions of the current
    CLAUDE.md — only the managed section is replaced with the default
    variant. The sidecar is validated (magic header must match) before any
    write. The sidecar is left in place after restore so repeated restores
    are safe.

    Returns True if the file was modified, False if the current state
    already matches the restored state (idempotent).
    """
    sidecar = _sidecar_path_for(claude_md_path)
    _validate_sidecar_header(sidecar)
    if not claude_md_path.exists():
        # Nothing to preserve; just install the default section fresh.
        default = _MANAGED_SECTION_DEFAULT
        _atomic_write(claude_md_path, default + "\n")
        return True

    current = claude_md_path.read_text(encoding="utf-8")
    before, _existing_managed, after = _split_managed(current)
    restored = before + _MANAGED_SECTION_DEFAULT + after
    if restored == current:
        return False
    _atomic_write(claude_md_path, restored)
    return True


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
