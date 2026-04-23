# Design — `/proj:save` note as inline parameter (todo 718)

**Status**: Approved
**Date**: 2026-04-23
**Scope**: `plugins/proj/skills/save/SKILL.md` — step 3 only.

---

## Problem

Every invocation of `/proj:save` currently triggers an interactive `AskUserQuestion` prompt:

> "Anything to add to session summary? (Enter to skip)"

For the common case the user has nothing to add, this is a forced round-trip that adds no value. It also prevents `/proj:save` from being used non-interactively in scripts, cron jobs, or agent chains.

## Goal

Remove the default prompt. Let the user pass the note inline as the slash-command argument. When nothing is passed, save with auto-extracted content only — no prompt.

## Constraints

- **Skill-file edit only.** No MCP changes, no Python changes, no schema changes, no new dependencies.
- **Consistent with other `proj` skills** — use `$ARGUMENTS` (the existing template variable populated by the Claude Code harness at invocation), like `/proj:todo`, `/proj:load`, `/proj:add-repo` already do.
- **No backward compatibility flag.** The old prompt is removed entirely; users who want to supply a note pass it inline.

## Design

### Step 3 (new)

```markdown
**3.** Note from `$ARGUMENTS`:
 - `$ARGUMENTS` empty → no user note; skip to step 4.
 - `$ARGUMENTS` non-empty → use the full string verbatim as the user note and include under "## User Note" in step 7's template.
```

Replaces the current step 3's `AskUserQuestion` call entirely. No fallback, no interactive branch.

### Other steps

Steps 1, 2, and 4–13 are unchanged. The `## User Note` block in step 7's session-file template is already conditional on "user provided something"; that condition now resolves to "`$ARGUMENTS` non-empty" rather than "user typed something in the interactive prompt".

### Usage examples (to be added near the existing Output section)

```markdown
## Usage

- `/proj:save` → skip, no prompt, no user note in file.
- `/proj:save Fixed flaky xdist test via per-test tmp dir` → the full argument string is included as the user note.
```

## Architecture

One file changes. No call graph shifts. Git tracking flush still fires from step 13. Wiki auto-ingest (step 11) still fires the subagent regardless of note presence.

## Components and data flow

```
user invokes /proj:save [ARGS]
        │
        ▼
harness binds $ARGUMENTS = ARGS (or empty)
        │
        ▼
step 1: session context
step 2: git reconcile (loop unchanged)
step 3: if $ARGUMENTS → note = $ARGUMENTS else note = None
step 4: synthesize auto-extracted content
step 7: template includes "## User Note <note>" iff note is not None
steps 8-13: unchanged
```

## Error handling

No new failure modes. Empty `$ARGUMENTS` is a normal code path, not an error. Non-empty strings are already serialized safely into Markdown (they're written to a session file via the existing `Write` tool, no shell expansion).

## Testing

Skills have no unit tests. Verification is manual:

- Run `/proj:save` with no args — confirm no prompt fires; session file has no `## User Note` section; rest of output unchanged.
- Run `/proj:save Test note here` — confirm the session file contains `## User Note\nTest note here` and everything else is unchanged.

## What this spec does not do

- Does **not** add a second way to trigger the old prompt (no `--interactive` flag, no `ask` keyword).
- Does **not** parse sub-commands or named flags. The argument is opaque free-form text.
- Does **not** touch any other `/proj:*` skill.
- Does **not** change the `mcp__proj__proj_session_context` MCP tool or any server code.

## Open questions

None. The mechanism is already used by sibling skills; the design is an edit to prose.
