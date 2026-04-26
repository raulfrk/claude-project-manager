# Wiki ingest todo-filter (todo 756)

**Date**: 2026-04-26
**Source todo**: 756 — `/proj:save wiki ingest: filter out todo-tracked status; only ingest concepts + decisions + insights`
**Status**: design approved, ready for plan

## Problem

Wiki ingest at end of `/proj:save` indiscriminately extracts entities from the session file, including todo-tracked state (in-flight todo IDs, "active improvement axes", ship/done status). Wiki gets stale "active" todos because:

- Todos close → wiki page is not updated (no `todo_complete` → wiki hook).
- Future readers querying the wiki see stale framing as current state.

**Concrete evidence**: `/wiki:query` for "improvement suggestions" on 2026-04-26 returned 3 todos (736, 737, 720) framed as "active" / "in-flight" — all DONE for 1+ days.

## Solution overview

Belt-and-suspenders, two layers:

- **Layer 1 (regex pre-filter)**: `/proj:save` strips todo-tracking content from the session file before passing it to the wiki ingest subagent.
- **Layer 2 (subagent prompt clause)**: ingest subagent prompt template adds explicit `EXCLUSION RULES` block instructing the LLM to skip todo IDs + status framing as a safety net for what the regex misses.
- **Backfill**: one-shot remediation of 3 known-stale wiki pages + repo-wide audit for `todo NNN` / status-phrase substrings.

Rejected alternative: `todo_complete` hook that auto-rewrites wiki pages mentioning the closing todo. Too much plumbing for behavior that ingest-time filtering prevents from accumulating.

## Layer 1: pre-filter session file in `/proj:save` step 11

### Placement

`plugins/proj/skills/save/SKILL.md` step 11. After the substance gate passes (decisions/insights/word-count threshold) and before the `Task` subagent dispatch.

### Algorithm

1. Read just-written session file (path from steps 5-7).
2. Apply 3 strip passes in order to the file body:
   - **Section strip**: remove `## Todos Worked On` heading + everything until next `## ` heading (or EOF). Multi-line regex anchored on heading + non-greedy lookahead. Heading match is exact, case-sensitive, leading whitespace allowed (matches actual `/proj:save` output). Pattern (illustrative): `(?ms)^## Todos Worked On\b.*?(?=^## |\Z)`.
   - **Todo-ID strip**: remove whole lines matching either:
     - `(?im)^.*\btodo[\s-]*\d+\b.*$` — explicit `todo NNN` references.
     - `(?im)^.*\b\d{3,4}\b.*\b(complete|completed|ship|shipped|close|closed|done|in-flight|active|ready|blocked)\b.*$` — bare 3-4 digit ID adjacent to action verbs.
   - **Status-phrase strip**: remove whole lines matching `(?im)^.*\b(in-flight|active improvement|active improvement axis|shipped this session|ready to start|blocked on|in progress|currently working)\b.*$`.
3. Write filtered body to `/tmp/wiki-ingest-<uuid4>.md` (uuid4 prevents collision across concurrent sessions).
4. Substitute tmp path into the subagent prompt: `{source}` = `session:/tmp/wiki-ingest-<uuid4>.md`. The `session:` prefix is preserved so the subagent uses the session-file reader path (not the generic file reader) — `section_map` category-hint logic still applies because `## Key Decisions` / `## Insights Discovered` headings survive filtering.
5. Try/finally: tmp file deleted on subagent return (success OR failure).
6. Subagent crash mid-flight → orphan tmp files in `/tmp/wiki-ingest-*.md`. Acceptable: `/tmp` cleared on reboot; uuid-prefixed names; manual cleanup trivial via glob.

### Why whole-line strip vs match-only strip

Removing only the matched substring leaves dangling sentence fragments like "Continued work on" (after stripping " todo 736"). Whole-line strip preserves paragraph readability for what remains, since session-file content is already mostly bullet-per-line.

### Original session file untouched

Strip applies only to the subagent input. `~/projects/tracking/<proj>/sessions/<filename>.md` is the project-side ground truth and stays as-written.

### Configurability

Hardcoded patterns. No new `~/.claude/wiki.yaml` knobs. Tune via PR if false positives surface in real usage.

## Layer 2: subagent prompt EXCLUSION RULES

### File

`plugins/wiki/skills/ingest/references/subagent-prompt.md`.

### Edit

Insert the following block between the `PROTOCOL:` heading and step 1:

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

### Scope

Applies to ALL ingest entrypoints (`/proj:save`, `/wiki:ingest`, `/wiki:bootstrap`) because they share the same template. Acceptable — same exclusion logic is correct for direct-call ingests of session files too.

## Backfill (bundled)

One-shot remediation of 3 known-stale pages + repo-wide audit. Spec includes the procedure; implementer executes interactively after Layer 1 + Layer 2 land.

### Targeted pages

1. **`[[parallel-orchestration-boundary-issues]]`**: `wiki_page_get` → strip "todo 736 — DETECTION axis" framing + any in-flight language. Keep concept + insights. `wiki_page_write(mode="update")`.
2. **`[[parallel-impl-orchestration]]`**: strip "Pattern not yet stress-tested when implementer reports BLOCKED" sentence. Keep pattern body. `wiki_page_write(mode="update")`.
3. **`[[phase2-polish-720]]`**: implementer reads page → asks user via `AskUserQuestion` whether to (a) rewrite as historical/lessons-learned page (strip todo refs + status, keep architectural decisions) or (b) `wiki_page_delete` if no reusable signal remains.

### Repo-wide audit

`wiki_page_list` → for each page, `wiki_page_get` → grep body for:
- `\btodo[\s-]*\d+\b`
- Status-phrase regex (same list as Layer 1).

Any page with matches → display to user → user decides per-page (rewrite / leave / delete). Sequential pass (not parallel) — low page count + lets user batch decisions.

### Cleanup

After all writes:
- `wiki_index_rebuild` (once, at end).
- `wiki_log_append(action="backfill", title="todo 756 stale-content remediation", body=<JSON summary of pages_updated/pages_deleted/pages_left>)`.

## Files to modify

- `plugins/proj/skills/save/SKILL.md` — step 11: insert pre-filter substeps before subagent dispatch.
- `plugins/wiki/skills/ingest/references/subagent-prompt.md` — insert EXCLUSION RULES block before PROTOCOL step 1.
- Tests (see below).

## Tests

### Layer 1 (filter logic)

New test module `plugins/proj/server/tests/test_save_wiki_filter.py` (or similar location matching project test layout — implementer confirms during plan):

- `test_strip_todos_worked_on_section`: input has `## Todos Worked On\n- ...\n- ...\n## Other Section\n` → output has `## Todos Worked On` block removed, `## Other Section` intact.
- `test_strip_todos_worked_on_at_eof`: same but section is last in file → strips to EOF correctly.
- `test_strip_todo_id_explicit`: line `Continued work on todo 736 today.` → stripped.
- `test_strip_todo_id_with_dash`: line `todo-736 was completed.` → stripped.
- `test_strip_bare_id_with_action_verb`: line `Closed 736 yesterday.` → stripped. Line `File main.py:736 has the bug.` → NOT stripped (no action verb).
- `test_strip_status_phrases`: line `This is an active improvement axis.` → stripped. Each phrase in the regex gets its own assertion.
- `test_preserves_decisions_section`: input has `## Key Decisions\n- ...\n` → unchanged after filter.
- `test_preserves_concept_content`: paragraph describing PYTHONPATH plugin loading → unchanged.
- `test_preserves_evidence_refs`: line `Path D was chosen — commit b7dae45 lifted the lib.` → unchanged.
- `test_uuid_in_tmp_path`: filtered output written to path matching `/tmp/wiki-ingest-[0-9a-f-]+\.md`.
- `test_tmp_cleanup_on_success`: subagent stub returns success → tmp file gone after function returns.
- `test_tmp_cleanup_on_failure`: subagent stub raises → tmp file gone after function returns (try/finally).

### Layer 2 (subagent prompt template)

- `test_subagent_prompt_contains_exclusion_rules`: read `plugins/wiki/skills/ingest/references/subagent-prompt.md` → assert the exclusion block string is present.
- `test_exclusion_block_precedes_protocol_step_1`: assert the substring `EXCLUSION RULES` appears at a position before `1. Resolve + read source` in the file.

### Backfill

No automated tests — interactive remediation pass. Implementer manually verifies after each `wiki_page_write` that the page no longer contains stripped patterns (grep check).

## Acceptance criteria

1. After landing Layer 1 + Layer 2, a `/proj:save` on a session file containing `## Todos Worked On`, `todo 999`, and `currently working on` produces wiki pages with none of those strings present.
2. Same `/proj:save` correctly extracts decisions/insights/concepts (e.g. a page about a new architectural pattern from `## Key Decisions` is created).
3. Backfill pass leaves the 3 named pages free of `todo 736` / `todo 720` / "stress-tested when implementer reports BLOCKED" substrings.
4. `wiki_log_read(action="backfill")` returns the backfill log entry.
5. All Layer 1 + Layer 2 unit tests pass.

## Out of scope

- Auto-update wiki on `todo_complete` (rejected — too much plumbing).
- Migration of existing wiki pages beyond the 3 named + audit hits (no time-machine for old ingests with no current evidence of staleness).
- Configurability via `~/.claude/wiki.yaml` (decided to hardcode; revisit if false positives surface).
- Heading-level robustness for `### Todos Worked On` or deeper (current `/proj:save` only emits H2; if that ever changes, add H3/H4 patterns then).

## Cross-references

- Todo 739 (wiki-query rule behavior gap) — related but orthogonal axis. Could bundle into a single "wiki research polish" cycle.
- Wiki page `[[memory-recall-gaps]]` — already lists "Stale memories" as CRITICAL; this fix is one mitigation.
