# Wiki Ingest Todo-Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip todo-tracked content from session files before wiki ingest so the wiki stops accumulating stale "active todo" framing.

**Architecture:** New pure-function filter library in `plugins/proj/server/server/lib/wiki_ingest_filter.py`, exposed as MCP tool `wiki_ingest_filter_session` in `plugins/proj/server/server/tools/wiki_filter.py`. Tool reads session file, applies 3 strip passes (section / todo-ID / status-phrase), writes filtered output to `/tmp/wiki-ingest-<uuid4>.md`, returns tmp path. `/proj:save` step 11 invokes the tool, substitutes the tmp path into the subagent prompt, deletes tmp on subagent return. Layer 2: `subagent-prompt.md` gets an EXCLUSION RULES block as LLM-side safety net. Backfill: deterministic edits to 2 known-stale wiki pages; follow-up todo for interactive page-3 + repo-wide audit.

**Tech Stack:** Python 3, FastMCP, pytest, ruff, basedpyright. Edits across `plugins/proj/server/`, `plugins/wiki/skills/ingest/references/`, `plugins/proj/skills/save/`, `~/.claude/wiki/pages/`.

**Spec:** `docs/superpowers/specs/2026-04-26-wiki-ingest-todo-filter-design.md`.

---

## Files Touched

**Create:**
- `plugins/proj/server/server/lib/wiki_ingest_filter.py` — pure filter function.
- `plugins/proj/server/server/tools/wiki_filter.py` — MCP tool wrapper.
- `plugins/proj/server/tests/test_wiki_ingest_filter.py` — unit tests for filter lib + MCP tool.

**Modify:**
- `plugins/proj/server/server/main.py` — register new tool module.
- `plugins/wiki/skills/ingest/references/subagent-prompt.md` — insert EXCLUSION RULES block before PROTOCOL step 1.
- `plugins/proj/skills/save/SKILL.md` — step 11: call `mcp__proj__wiki_ingest_filter_session` before subagent dispatch, use returned tmp path, delete tmp on return.
- `~/.claude/wiki/pages/pitfalls/parallel-orchestration-boundary-issues.md` — strip todo-736 framing.
- `~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md` — strip "stress-tested when implementer reports BLOCKED" sentence.

**Out of scope (deferred to follow-up todo):**
- `~/.claude/wiki/pages/decisions/phase2-polish-720.md` — needs interactive user judgment (rewrite vs delete).
- Repo-wide wiki audit for `todo NNN` / status-phrase substrings — needs interactive per-page user decisions.

---

## Task 1: Filter library + tests (TDD)

**Files:**
- Create: `plugins/proj/server/server/lib/wiki_ingest_filter.py`
- Test: `plugins/proj/server/tests/test_wiki_ingest_filter.py`

- [ ] **Step 1: Write failing tests for the pure filter function**

Create `plugins/proj/server/tests/test_wiki_ingest_filter.py`:

```python
"""Tests for wiki_ingest_filter pure function."""

from __future__ import annotations

from server.lib.wiki_ingest_filter import filter_session_text


class TestSectionStrip:
    def test_strip_todos_worked_on_section(self) -> None:
        text = (
            "## Key Decisions\n"
            "- Decided X\n"
            "\n"
            "## Todos Worked On\n"
            "- 736: completed\n"
            "- 737: in progress\n"
            "\n"
            "## Insights Discovered\n"
            "- Insight A\n"
        )
        out = filter_session_text(text)
        assert "## Todos Worked On" not in out
        assert "736: completed" not in out
        assert "## Key Decisions" in out
        assert "Decided X" in out
        assert "## Insights Discovered" in out
        assert "Insight A" in out

    def test_strip_todos_worked_on_at_eof(self) -> None:
        text = (
            "## Key Decisions\n"
            "- Decided X\n"
            "\n"
            "## Todos Worked On\n"
            "- 736: completed\n"
        )
        out = filter_session_text(text)
        assert "## Todos Worked On" not in out
        assert "736: completed" not in out
        assert "## Key Decisions" in out

    def test_no_todos_section_no_change_to_sections(self) -> None:
        text = "## Key Decisions\n- Decided X\n\n## Insights Discovered\n- Insight A\n"
        out = filter_session_text(text)
        assert "## Key Decisions" in out
        assert "## Insights Discovered" in out


class TestTodoIdStrip:
    def test_strip_todo_id_explicit(self) -> None:
        text = "Continued work on todo 736 today.\nUnrelated line.\n"
        out = filter_session_text(text)
        assert "todo 736" not in out
        assert "Unrelated line." in out

    def test_strip_todo_id_with_dash(self) -> None:
        text = "todo-736 was completed.\nUnrelated.\n"
        out = filter_session_text(text)
        assert "todo-736" not in out
        assert "Unrelated." in out

    def test_strip_todo_id_case_insensitive(self) -> None:
        text = "TODO 999 needs attention.\nKeep me.\n"
        out = filter_session_text(text)
        assert "TODO 999" not in out
        assert "Keep me." in out

    def test_strip_bare_id_with_action_verb(self) -> None:
        text = "Closed 736 yesterday.\nKeep me.\n"
        out = filter_session_text(text)
        assert "Closed 736" not in out
        assert "Keep me." in out

    def test_keep_bare_id_without_action_verb(self) -> None:
        text = "File main.py:736 has the bug.\n"
        out = filter_session_text(text)
        assert "main.py:736" in out


class TestStatusPhraseStrip:
    def test_strip_in_flight(self) -> None:
        text = "This work is in-flight.\nKeep this.\n"
        out = filter_session_text(text)
        assert "in-flight" not in out
        assert "Keep this." in out

    def test_strip_active_improvement_axis(self) -> None:
        text = "The active improvement axis here is robustness.\nKeep this.\n"
        out = filter_session_text(text)
        assert "active improvement axis" not in out
        assert "Keep this." in out

    def test_strip_shipped_this_session(self) -> None:
        text = "Shipped this session: feature X.\nKeep this.\n"
        out = filter_session_text(text)
        assert "Shipped this session" not in out
        assert "Keep this." in out

    def test_strip_ready_to_start(self) -> None:
        text = "Items ready to start include A.\nKeep this.\n"
        out = filter_session_text(text)
        assert "ready to start" not in out
        assert "Keep this." in out

    def test_strip_blocked_on(self) -> None:
        text = "Currently blocked on dep Y.\nKeep this.\n"
        out = filter_session_text(text)
        assert "blocked on" not in out
        assert "Keep this." in out

    def test_strip_in_progress(self) -> None:
        text = "Work in progress on Z.\nKeep this.\n"
        out = filter_session_text(text)
        assert "in progress" not in out
        assert "Keep this." in out

    def test_strip_currently_working(self) -> None:
        text = "Currently working on W.\nKeep this.\n"
        out = filter_session_text(text)
        assert "currently working" not in out
        assert "Keep this." in out


class TestPreservesContent:
    def test_preserves_decisions_section(self) -> None:
        text = "## Key Decisions\n- Picked path D over A.\n- Reason: lower friction.\n"
        out = filter_session_text(text)
        assert out == text

    def test_preserves_concept_paragraph(self) -> None:
        text = (
            "PYTHONPATH plugin loading sidesteps namespace collision because\n"
            "start.sh execs the shared venv python directly with PYTHONPATH=$DIR.\n"
        )
        out = filter_session_text(text)
        assert out == text

    def test_preserves_evidence_refs(self) -> None:
        text = "Path D was chosen — commit b7dae45 lifted the lib.\n"
        out = filter_session_text(text)
        assert out == text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/proj/server && uv run pytest tests/test_wiki_ingest_filter.py -v`
Expected: ImportError or FAIL because `wiki_ingest_filter` module does not exist.

- [ ] **Step 3: Implement the filter library**

Create `plugins/proj/server/server/lib/wiki_ingest_filter.py`:

```python
"""Pre-ingest filter for session files passed to wiki ingest subagent.

Strips todo-tracked content (todo IDs, status framing, "## Todos Worked On"
section) so wiki entities never pick up in-flight project state. See spec
docs/superpowers/specs/2026-04-26-wiki-ingest-todo-filter-design.md.
"""

from __future__ import annotations

import re

# Section heading + everything until next H2 or EOF.
_TODOS_WORKED_ON_RE = re.compile(
    r"(?ms)^[ \t]*## Todos Worked On\b.*?(?=^[ \t]*## |\Z)"
)

# Whole-line strip: explicit "todo NNN" / "todo-NNN" references.
_TODO_ID_EXPLICIT_RE = re.compile(
    r"(?im)^.*\btodo[\s-]*\d+\b.*$\n?"
)

# Whole-line strip: bare 3-4 digit id near an action/state verb.
_TODO_ID_BARE_RE = re.compile(
    r"(?im)^.*\b\d{3,4}\b.*\b(?:complete|completed|ship|shipped|close|closed|done|in-flight|active|ready|blocked)\b.*$\n?"
)

# Whole-line strip: status-framing phrases.
_STATUS_PHRASE_RE = re.compile(
    r"(?im)^.*\b(?:in-flight|active improvement axis|active improvement|shipped this session|ready to start|blocked on|in progress|currently working)\b.*$\n?"
)


def filter_session_text(text: str) -> str:
    """Apply 3 strip passes in order: section, todo-id, status-phrase.

    Returns the filtered text. Whole-line strip is used (not match-only) so
    paragraph readability is preserved for what remains.
    """
    out = _TODOS_WORKED_ON_RE.sub("", text)
    out = _TODO_ID_EXPLICIT_RE.sub("", out)
    out = _TODO_ID_BARE_RE.sub("", out)
    out = _STATUS_PHRASE_RE.sub("", out)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/proj/server && uv run pytest tests/test_wiki_ingest_filter.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/server/lib/wiki_ingest_filter.py plugins/proj/server/tests/test_wiki_ingest_filter.py
git commit -m "feat(proj/lib): wiki_ingest_filter pure function + tests"
```

---

## Task 2: MCP tool wrapper + registration

**Files:**
- Create: `plugins/proj/server/server/tools/wiki_filter.py`
- Modify: `plugins/proj/server/server/main.py`
- Test: append to `plugins/proj/server/tests/test_wiki_ingest_filter.py`

- [ ] **Step 1: Write failing test for the MCP tool**

Append to `plugins/proj/server/tests/test_wiki_ingest_filter.py`:

```python
import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import call_tool


class TestWikiFilterTool:
    @pytest.mark.anyio()
    async def test_tool_writes_tmp_and_strips(self, tmp_path: Any, mcp_app: Any) -> None:
        session = tmp_path / "session.md"
        session.write_text(
            "## Key Decisions\n"
            "- Decided X\n"
            "\n"
            "## Todos Worked On\n"
            "- 736: completed\n"
            "\n"
            "## Insights Discovered\n"
            "- Insight A\n"
        )
        result = json.loads(
            await call_tool(mcp_app, "wiki_ingest_filter_session", session_path=str(session))
        )
        assert result["status"] == "filtered"
        tmp_path_str = result["tmp_path"]
        assert re.match(r"^/tmp/wiki-ingest-[0-9a-f-]+\.md$", tmp_path_str)
        body = Path(tmp_path_str).read_text()
        assert "## Todos Worked On" not in body
        assert "736: completed" not in body
        assert "## Key Decisions" in body
        assert "## Insights Discovered" in body
        # Cleanup so subsequent tests don't accumulate
        Path(tmp_path_str).unlink()

    @pytest.mark.anyio()
    async def test_tool_missing_session_returns_error(self, tmp_path: Any, mcp_app: Any) -> None:
        result = json.loads(
            await call_tool(
                mcp_app,
                "wiki_ingest_filter_session",
                session_path=str(tmp_path / "does-not-exist.md"),
            )
        )
        assert result["status"] == "error"
        assert "not found" in result["error"].lower() or "no such" in result["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/proj/server && uv run pytest tests/test_wiki_ingest_filter.py::TestWikiFilterTool -v`
Expected: FAIL — tool not registered.

- [ ] **Step 3: Create the MCP tool**

Create `plugins/proj/server/server/tools/wiki_filter.py`:

```python
"""MCP tool: filter a session file before wiki ingest dispatch.

See spec docs/superpowers/specs/2026-04-26-wiki-ingest-todo-filter-design.md.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib.wiki_ingest_filter import filter_session_text

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register(app: "FastMCP") -> None:
    """Register wiki_ingest_filter_session tool."""

    @app.tool(
        description=(
            "Filter a session file for wiki ingest by stripping todo-tracked "
            "content (todo IDs, status framing, '## Todos Worked On' section). "
            "Writes filtered output to /tmp/wiki-ingest-<uuid4>.md and returns "
            "the tmp path. Caller is responsible for deleting the tmp file "
            "after the wiki ingest subagent returns."
        )
    )
    def wiki_ingest_filter_session(session_path: str) -> str:
        src = Path(session_path)
        if not src.is_file():
            return json.dumps(
                {"status": "error", "error": f"Session file not found: {session_path}"}
            )
        try:
            text = src.read_text(encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to read session file: %s", session_path)
            return json.dumps({"status": "error", "error": f"Read failed: {exc}"})

        filtered = filter_session_text(text)
        tmp_path = Path("/tmp") / f"wiki-ingest-{uuid.uuid4()}.md"
        try:
            tmp_path.write_text(filtered, encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to write tmp file: %s", tmp_path)
            return json.dumps({"status": "error", "error": f"Write failed: {exc}"})

        return json.dumps(
            {
                "status": "filtered",
                "tmp_path": str(tmp_path),
                "original_bytes": len(text.encode("utf-8")),
                "filtered_bytes": len(filtered.encode("utf-8")),
            }
        )
```

- [ ] **Step 4: Wire the tool into main.py**

Edit `plugins/proj/server/server/main.py`. Add `wiki_filter` to the import block + add `wiki_filter.register(mcp)` after `sandbox.register(mcp)`:

```python
from server.tools import (
    config,
    content,
    context,
    decisions,
    digest,
    explore,
    git,
    jira_sync,
    knowledge,
    migrate,
    perms_grant,
    perms_sync,
    projects,
    sandbox,
    sync,
    todoist_full_sync,
    todos,
    tracking_git,
    trello_full_sync,
    trello_sync,
    wiki_filter,  # ← add
)
# ... after existing register calls:
sandbox.register(mcp)
wiki_filter.register(mcp)  # ← add
```

(Preserve the existing import order; insert `wiki_filter` alphabetically after `trello_sync`. Confirm by reading `main.py` first — order may differ.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd plugins/proj/server && uv run pytest tests/test_wiki_ingest_filter.py -v`
Expected: ALL pass (lib tests + tool tests).

- [ ] **Step 6: Commit**

```bash
git add plugins/proj/server/server/tools/wiki_filter.py plugins/proj/server/server/main.py plugins/proj/server/tests/test_wiki_ingest_filter.py
git commit -m "feat(proj/tool): wiki_ingest_filter_session MCP tool + registration"
```

---

## Task 3: Wiki subagent prompt EXCLUSION RULES

**Files:**
- Modify: `plugins/wiki/skills/ingest/references/subagent-prompt.md`
- Test: `plugins/wiki/server/tests/test_subagent_prompt.py` (new)

- [ ] **Step 1: Write failing test for the prompt content**

Create `plugins/wiki/server/tests/test_subagent_prompt.py`:

```python
"""Test that subagent prompt template contains the EXCLUSION RULES block."""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "ingest"
    / "references"
    / "subagent-prompt.md"
)


def test_prompt_file_exists() -> None:
    assert PROMPT_PATH.is_file(), f"Prompt file missing: {PROMPT_PATH}"


def test_exclusion_rules_block_present() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "EXCLUSION RULES" in content
    assert "Todo IDs or any \"todo NNN\" references." in content
    assert "In-flight/active/shipped/ready/blocked status framing." in content
    assert "## Todos Worked On" in content
    assert "Concepts, patterns, designs (architectural reuse value)." in content
    assert "Decisions with rejected alternatives + trade-offs." in content
    assert "Pitfalls + technical insights (gotchas, surprising behavior)." in content
    assert "EVIDENCE" in content


def test_exclusion_block_precedes_protocol_step_1() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    excl_idx = content.find("EXCLUSION RULES")
    step1_idx = content.find("1. Resolve + read source")
    assert excl_idx != -1
    assert step1_idx != -1
    assert excl_idx < step1_idx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/wiki/server && uv run pytest tests/test_subagent_prompt.py -v`
Expected: FAIL — `EXCLUSION RULES` not in prompt yet.

- [ ] **Step 3: Edit subagent-prompt.md to add EXCLUSION RULES block**

In `plugins/wiki/skills/ingest/references/subagent-prompt.md`, find the line `PROTOCOL:` (currently around line 33) and insert this block immediately before it (still inside the fenced code block):

```
EXCLUSION RULES — do NOT extract these as wiki entities:
- Todo IDs or any "todo NNN" references.
- In-flight/active/shipped/ready/blocked status framing.
- Anything from a "## Todos Worked On" section if present.
- Project-internal tracking state (NOTES.md heading conventions, todo-graph batches, etc.).

DO extract:
- Concepts, patterns, designs (architectural reuse value).
- Decisions with rejected alternatives + trade-offs.
- Pitfalls + technical insights (gotchas, surprising behavior).

Commit SHAs and file paths within these categories are EVIDENCE — keep them.

```

The existing `PROTOCOL:` heading and step 1 (`1. Resolve + read source...`) remain unchanged below.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/wiki/server && uv run pytest tests/test_subagent_prompt.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/skills/ingest/references/subagent-prompt.md plugins/wiki/server/tests/test_subagent_prompt.py
git commit -m "feat(wiki/ingest): EXCLUSION RULES block in subagent prompt"
```

---

## Task 4: Wire filter into /proj:save step 11

**Files:**
- Modify: `plugins/proj/skills/save/SKILL.md`
- Test: `plugins/proj/server/tests/test_save_skill_wiki_filter_wiring.py` (new — content-grep test)

- [ ] **Step 1: Write failing test that the skill mentions the new tool**

Create `plugins/proj/server/tests/test_save_skill_wiki_filter_wiring.py`:

```python
"""Test that /proj:save SKILL.md step 11 invokes the new filter tool."""

from __future__ import annotations

from pathlib import Path

SKILL_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "save"
    / "SKILL.md"
)


def test_skill_calls_wiki_ingest_filter_session() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    assert "mcp__proj__wiki_ingest_filter_session" in content


def test_skill_uses_tmp_path_for_subagent_source() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    # tmp_path returned by the tool must be substituted into {source}
    assert "tmp_path" in content
    # Cleanup language must mention deleting the tmp file
    assert "tmp" in content.lower() and ("delete" in content.lower() or "unlink" in content.lower() or "rm " in content.lower())


def test_skill_declares_new_tool_in_allowed_tools() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    # Frontmatter `allowed-tools:` must include the new tool
    assert "mcp__proj__wiki_ingest_filter_session" in content.split("---", 2)[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/proj/server && uv run pytest tests/test_save_skill_wiki_filter_wiring.py -v`
Expected: FAIL — skill does not yet reference the new tool.

- [ ] **Step 3: Edit save SKILL.md step 11**

In `plugins/proj/skills/save/SKILL.md`:

1. Add `mcp__proj__wiki_ingest_filter_session` to the `allowed-tools:` line in frontmatter (line 4). Insert after `mcp__proj__config_load` for alphabetic-ish order.

2. Replace step 11's "Gate pass" branch (currently the bullet under `Gate pass → spawn forked subagent via Task:`) with this expanded version:

```markdown
   - Gate pass → pre-filter session file then spawn forked subagent:
     - `mcp__proj__wiki_ingest_filter_session(session_path=<tracking_dir>/<name>/sessions/<filename>)` → parse JSON → on `status: "error"`: warn "Wiki ingest skipped: filter failed: <error>." + skip dispatch + continue to step 12. On `status: "filtered"`: capture `tmp_path`.
     - Spawn forked subagent via `Task`:
       - `subagent_type="general-purpose"`
       - `description="Wiki ingest session file"`
       - `prompt` = contents of `plugins/wiki/skills/ingest/references/subagent-prompt.md` (read via `Read`) w/ `{source}` = `session:<tmp_path>`, `{scope}` = `project:<name>` (from step 1), `{wiki_config}` = JSON of `~/.claude/wiki.yaml` + `~/.claude/wiki/config.yaml` (read via `Read`).
     - On subagent return (success OR failure): `Bash(rm -f <tmp_path>)` to clean up the tmp file.
```

(Leave the surrounding bullets — config_load gate check, "Both false → skip", gate-fail branch, success/failure messages — unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/proj/server && uv run pytest tests/test_save_skill_wiki_filter_wiring.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/skills/save/SKILL.md plugins/proj/server/tests/test_save_skill_wiki_filter_wiring.py
git commit -m "feat(proj/save): step 11 pre-filters session file via wiki_ingest_filter_session"
```

---

## Task 5: Backfill stale wiki page #1 (parallel-orchestration-boundary-issues)

**Files:**
- Modify: `~/.claude/wiki/pages/pitfalls/parallel-orchestration-boundary-issues.md`

- [ ] **Step 1: Read the page to identify the stale strings**

Run: `Read ~/.claude/wiki/pages/pitfalls/parallel-orchestration-boundary-issues.md`. Identify any string containing `todo 736`, `DETECTION axis`, or in-flight status framing.

- [ ] **Step 2: Strip stale references via Edit**

For each identified stale string, use the `Edit` tool to remove the offending sentence/clause while preserving surrounding architectural content. Specifically: any phrasing along the lines of "todo 736 — DETECTION axis" or sentences framing past work as currently in progress.

If the page becomes incoherent after strips (e.g. transitions broken), rewrite the affected paragraph to flow without the removed references. Aim: the page reads as a stable, evergreen pitfall description, not a session log.

- [ ] **Step 3: Verify cleanly via grep**

Run: `grep -E '\btodo[\s-]*[0-9]+\b' ~/.claude/wiki/pages/pitfalls/parallel-orchestration-boundary-issues.md`
Expected: no matches.

Run: `grep -E 'in-flight|active improvement|shipped this session|in progress|currently working' ~/.claude/wiki/pages/pitfalls/parallel-orchestration-boundary-issues.md`
Expected: no matches.

- [ ] **Step 4: Update last_ingested in frontmatter**

If the page has a `last_ingested:` frontmatter field, update it to today's UTC date (e.g. `2026-04-26T00:00:00Z`). This signals the page was touched.

- [ ] **Step 5: Commit**

This wiki lives outside the repo (`~/.claude/wiki/`), so no project commit is needed for the page edit itself. Skip the commit step. Move on.

---

## Task 6: Backfill stale wiki page #2 (parallel-impl-orchestration)

**Files:**
- Modify: `~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md`

- [ ] **Step 1: Read the page**

Run: `Read ~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md`. Identify the sentence "Pattern not yet stress-tested when implementer reports BLOCKED" or similar in-flight phrasing.

- [ ] **Step 2: Strip the stale sentence via Edit**

Use the `Edit` tool to remove the active-state language. The pattern body itself (concepts about parallel orchestration) stays intact.

- [ ] **Step 3: Verify**

Run: `grep -E 'stress-tested when implementer reports|in-flight|active improvement|in progress|currently working' ~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md`
Expected: no matches.

- [ ] **Step 4: Update last_ingested**

Same as Task 5 step 4.

- [ ] **Step 5: Skip commit (page outside repo).**

---

## Task 7: Create follow-up todo for interactive backfill

**Files:** none (creates a new project todo).

- [ ] **Step 1: Create the follow-up todo**

Run via `mcp__plugin_proj_proj__todo_add`:

```
title: "Wiki backfill (interactive): phase2-polish-720 page + repo-wide audit for todo-NNN / status-phrase substrings"
priority: medium
tags: ["wiki", "backfill", "manual", "follow-up-756"]
notes: |
  Spec docs/superpowers/specs/2026-04-26-wiki-ingest-todo-filter-design.md
  bundled this backfill, but autonomous execution skipped it because both
  items need user judgment.

  ## Sub-task 1: phase2-polish-720 page
  - Read ~/.claude/wiki/pages/decisions/phase2-polish-720.md
  - Decide: rewrite as historical/lessons-learned page (strip todo refs +
    status, keep architectural decisions made during 720) OR wiki_page_delete
    if no reusable signal remains after strip.
  - User picks via AskUserQuestion.

  ## Sub-task 2: repo-wide audit
  - wiki_page_list → for each page, wiki_page_get → grep body for:
    * \\btodo[\\s-]*\\d+\\b
    * (in-flight|active improvement|shipped this session|ready to start|blocked on|in progress|currently working)
  - For each page with matches: display to user, user decides per-page
    (rewrite / leave / delete). Sequential pass.

  ## Cleanup
  - wiki_index_rebuild once at end.
  - wiki_log_append(action="backfill", title="todo 756 stale-content remediation",
    body=<JSON summary>).

  Auto-added by Claude during todo 756 autonomous impl — interactive parts deferred.
```

- [ ] **Step 2: Verify todo created**

Run: `mcp__plugin_proj_proj__todo_list` filtered by tag `follow-up-756`. Expect 1 todo.

- [ ] **Step 3: Skip commit (todos managed by proj plugin, not source-controlled here).**

---

## Task 8: Run full test suite

- [ ] **Step 1: Run proj plugin tests**

Run: `cd plugins/proj/server && uv run pytest -v`
Expected: ALL pass (existing tests unaffected, new tests green).

- [ ] **Step 2: Run wiki plugin tests**

Run: `cd plugins/wiki/server && uv run pytest -v`
Expected: ALL pass.

- [ ] **Step 3: Run lint**

Run: `cd plugins/proj/server && uv run ruff check . && uv run ruff format --check .`
Run: `cd plugins/wiki/server && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 4: Run basedpyright on changed Python files**

Run: `cd plugins/proj/server && uv run basedpyright server/lib/wiki_ingest_filter.py server/tools/wiki_filter.py tests/test_wiki_ingest_filter.py`
Expected: 0 errors, 0 warnings.

- [ ] **Step 5: Commit any formatting fixes**

If ruff/basedpyright surfaced fixes:
```bash
git add -u
git commit -m "style: ruff/basedpyright fixes"
```

---

## Task 9: Mark todo 756 complete + close out

- [ ] **Step 1: Mark todo 756 complete**

Run: `mcp__plugin_proj_proj__todo_complete(todo_id="756")`.

- [ ] **Step 2: Verify**

Run: `mcp__plugin_proj_proj__todo_get(todo_id="756")` → `status: "completed"`.
