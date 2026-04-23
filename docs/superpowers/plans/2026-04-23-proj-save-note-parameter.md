# `/proj:save` inline note parameter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the forced "Anything to add?" prompt from `/proj:save` and replace it with an opt-in inline argument via `$ARGUMENTS`.

**Architecture:** Edit a single skill file (prose + YAML frontmatter Markdown). No code, no schema, no tests. The Claude Code harness already populates `$ARGUMENTS` for `/proj:*` slash commands; the pattern is used by `/proj:todo`, `/proj:load`, `/proj:add-repo`.

**Tech Stack:** Markdown. No language tooling.

**Spec:** `docs/superpowers/specs/2026-04-23-proj-save-note-parameter-design.md` (commit `a2b810f`).

**Risk level:** Very low. One skill file edit. No automated tests for skills — verification is manual invocation.

---

## File Structure

- Modify: `plugins/proj/skills/save/SKILL.md` — step 3 (interactive prompt → `$ARGUMENTS` read); optionally add a brief **Usage** block.
- Everything else (steps 1, 2, 4–13; Prerequisites, Err Handling, Output sections) stays byte-identical.

---

## Task 1: Replace step 3 with `$ARGUMENTS` read

**Files:**
- Modify: `plugins/proj/skills/save/SKILL.md` — lines around step 3 (currently line 19 in the on-disk version).

- [ ] **Step 1: Read the current file** to confirm the exact wording before editing.

```bash
sed -n '15,25p' plugins/proj/skills/save/SKILL.md
```

Expected: line 19 reads `**3.** Ask user: "Anything to add to session summary? (Enter to skip)"`.

- [ ] **Step 2: Replace step 3 wording.**

Find:

```
**3.** Ask user: "Anything to add to session summary? (Enter to skip)"
```

Replace with:

```
**3.** Note from `$ARGUMENTS`:
 - `$ARGUMENTS` empty → no user note; skip to step 4.
 - `$ARGUMENTS` non-empty → use the full string verbatim as the user note; include under "## User Note" in step 7's template.
```

Use the Edit tool with `old_string` = the current step-3 line and `new_string` = the three-line block above.

- [ ] **Step 3: Verify the edit applied cleanly.**

```bash
sed -n '19,22p' plugins/proj/skills/save/SKILL.md
```

Expected: three lines beginning with `**3.** Note from \`$ARGUMENTS\`:`, followed by the two `-` bullets.

- [ ] **Step 4: Confirm step 4's reference still reads correctly.**

```bash
grep -n 'User provided note in step 3' plugins/proj/skills/save/SKILL.md
```

Expected: exactly one match (existing line). No change needed — the phrase "user provided note in step 3" still applies; the provision mechanism just shifted from interactive prompt to argument read.

---

## Task 2: Add a brief Usage block

**Files:**
- Modify: `plugins/proj/skills/save/SKILL.md` — append after the existing `## Output` section.

- [ ] **Step 1: Read the current tail of the file.**

```bash
sed -n '95,$p' plugins/proj/skills/save/SKILL.md
```

Expected: section `## Output` at the end of the file with one paragraph.

- [ ] **Step 2: Append a Usage section.**

Use the Edit tool to append after the last line of `## Output`:

```markdown

## Usage

- `/proj:save` → save w/o user note. No prompt.
- `/proj:save <free-form note>` → save w/ user note = the full argument string.
```

(The blank line before `## Usage` is intentional — Markdown section separation.)

- [ ] **Step 3: Verify the section landed.**

```bash
grep -n '^## Usage' plugins/proj/skills/save/SKILL.md
```

Expected: exactly one match, after `## Output`.

---

## Task 3: Manual verification

**Files:** None modified — this task runs the changed skill and confirms behaviour.

- [ ] **Step 1: Invoke `/proj:save` with no argument in a scratch conversation.**

Expected behaviour per the new step 3:

- No `AskUserQuestion` fires for "Anything to add?".
- Session file is written under `<tracking_dir>/<name>/sessions/session-<date>[-N].md`.
- The session file has NO `## User Note` section.
- Git reconcile, decision log, wiki ingest, tracking flush all proceed as before.

If an `AskUserQuestion` for a session note still fires → task 1 edit is wrong; redo step 2 of Task 1.

- [ ] **Step 2: Invoke `/proj:save verification probe` in a scratch conversation.**

Expected behaviour:

- No `AskUserQuestion` prompt for a session note.
- Session file contains `## User Note\nverification probe` at the appropriate position (per step 7's template).
- Everything else identical to step 1.

If the note doesn't land in the session file → step 7's template integration is broken (the `<only if user provided something>` conditional is not resolving to the new source); adjust Task 1 step 2's wording to make the binding explicit.

- [ ] **Step 3: (Optional) Invoke `/proj:save   multi-word note with leading whitespace   `.**

Expected behaviour:

- Session file's `## User Note` block contains the argument verbatim, including leading/trailing whitespace (or Markdown-safe trimmed — either is acceptable; document whichever way the harness passes `$ARGUMENTS`).

---

## Task 4: Commit

**Files:**
- Staged: `plugins/proj/skills/save/SKILL.md`

- [ ] **Step 1: Stage + commit.**

```bash
git add plugins/proj/skills/save/SKILL.md
git commit -m "$(cat <<'EOF'
feat(proj/718): /proj:save takes note via $ARGUMENTS instead of prompting

Removes the interactive "Anything to add to session summary?" prompt
from step 3. Users now pass the note inline:

  /proj:save                 # no note
  /proj:save Fixed xdist flake  # note = "Fixed xdist flake"

Matches the $ARGUMENTS pattern already used by /proj:todo, /proj:load,
and /proj:add-repo. Design spec:
docs/superpowers/specs/2026-04-23-proj-save-note-parameter-design.md.

No MCP / Python / schema changes. Skill file edit only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: pre-commit hooks pass (skill file is Markdown; no ruff / basedpyright / _shared-version checks apply). One commit created.

- [ ] **Step 2: Verify commit landed and working tree is clean.**

```bash
git log --oneline -1
git status --short
```

Expected: last commit is `feat(proj/718): ...`; status is clean.

---

## Verification summary

After all four tasks:

- `plugins/proj/skills/save/SKILL.md` has step 3 rewritten and a new `## Usage` block at the end.
- Manual tests in Task 3 show no prompt when `$ARGUMENTS` is empty and a `## User Note` section when it isn't.
- One commit on the current branch (`dev` per the working tree).

No other files change. No CI matrix rows need update (skills aren't tested in CI). No `_shared` version bump (no `_shared` edits).

---

## What this plan does not do

- Does **not** add a `--interactive`, `ask`, or any other fallback keyword that re-enables the prompt. If the user wants a note they pass it inline; otherwise no prompt.
- Does **not** add unit or integration tests (skills have no test harness in this repo).
- Does **not** touch any `mcp__proj__*` tool, CLI, or Python code.
- Does **not** touch sibling skills (`/proj:todo`, `/proj:load`, etc.). They already follow the `$ARGUMENTS` pattern this task adopts.
