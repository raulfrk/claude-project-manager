# CLAUDE.md Batch Completion Rule Update — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the project CLAUDE.md "Batch Completion Enforcement" section to reference the current `mcp__plugin_proj_proj__todo_complete` tool with `todo_ids=[...]` instead of the removed `mcp__proj__todo_batch_complete`.

**Architecture:** Single-file documentation edit. No code, no tests. The replacement text is fully specified in the spec.

**Tech Stack:** Markdown.

**Spec:** `docs/superpowers/specs/2026-04-26-claudemd-batch-completion-rule-design.md`
**Todo:** 738

---

## File Structure

| File | Action | Lines | Responsibility |
|---|---|---|---|
| `/home/raul/projects/claude-project-manager/CLAUDE.md` | Modify | 47-55 | Replace stale "Batch Completion Enforcement" section text |

No other files. No tests (doc-only).

---

## Task 1: Replace the "Batch Completion Enforcement" section

**Files:**
- Modify: `CLAUDE.md` (lines 47-55, the entire `## Batch Completion Enforcement` section through the blank line before `## E2E TUI Snapshot Flakes`)

- [ ] **Step 1: Confirm current section content**

Run from repo root:

```bash
sed -n '47,55p' CLAUDE.md
```

Expected output:

```
## Batch Completion Enforcement

**Always use `mcp__proj__todo_batch_complete` when marking 2 or more todos done in the same operation.** Never loop `todo_complete` across multiple ids. The batch tool:
- Validates, deduplicates, and atomically saves all ids under a cross-process file lock (`threading.Lock` + `fcntl.flock`).
- Fires ONE aggregated hook chain per integration (Todoist `todoist_complete_tasks`, Trello `trello_batch_archive_cards`, Jira `jira_update_issues`) instead of N sequential chains.
- Returns a `_hooks.structured_errors` sidecar that identifies which integration/ids failed per hook.

Single-todo completion continues to use `mcp__proj__todo_complete`.
```

If the output differs from the above (e.g., section was already partially updated, or moved), STOP and ask the user before proceeding — line numbers in this plan may be stale.

- [ ] **Step 2: Apply the replacement**

Use the Edit tool. The `old_string` parameter is the exact 9-line block from Step 1's expected output. The `new_string` is:

```
## Batch Completion Enforcement

**Always pass `todo_ids=[...]` to `mcp__plugin_proj_proj__todo_complete` when marking 2+ todos done in the same operation.** Never loop the tool with one `todo_id` per call. The batch path:
- Routes via `todo_ids` (list) parameter — atomic, deduplicated, saved under a single cross-process file lock.
- Fires ONE aggregated hook chain per integration (Todoist `todoist_complete_tasks`, Trello `trello_batch_archive_cards`, Jira `jira_update_issues`) instead of N sequential chains.
- Returns `_hooks.structured_errors` listing per-integration failures by id.

Single-todo completion: pass `todo_id="..."` (or `todo_ids=["..."]` — both work).
```

- [ ] **Step 3: Verify the replacement**

Run:

```bash
sed -n '47,55p' CLAUDE.md
```

Expected: prints the new replacement block exactly. The blank line at line 55 before `## E2E TUI Snapshot Flakes` (line 56) must remain intact.

Run:

```bash
grep -c 'mcp__proj__todo_batch_complete\|mcp__proj__todo_complete' CLAUDE.md
```

Expected: `0` (no remaining stale tool refs).

Run:

```bash
grep -c 'mcp__plugin_proj_proj__todo_complete' CLAUDE.md
```

Expected: `1` (the single ref in the rewritten section).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
fix(claudemd/738): batch-completion rule refs current todo_complete tool

The "Batch Completion Enforcement" section in the project CLAUDE.md
mandated `mcp__proj__todo_batch_complete`, which was removed when batch
completion was unified into `mcp__plugin_proj_proj__todo_complete` (the
unified tool accepts either `todo_id` or `todo_ids`, with the batch
path triggering on `todo_ids`). Agents following the old rule failed
with "tool not found".

Rewrites the section to point at the current tool name (with the
`mcp__plugin_proj_proj__` namespace prefix) and the `todo_ids=[...]`
parameter form. Atomicity + single-hook-chain claims preserved;
implementation-detail mentions (threading.Lock + fcntl.flock) dropped
since they're internal, not API contract.

Spec: docs/superpowers/specs/2026-04-26-claudemd-batch-completion-rule-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hooks pass (the file is markdown, so most are skipped).

---

## Acceptance Criteria

After Task 1 completes:

1. ✅ `grep 'mcp__proj__todo_batch_complete\|mcp__proj__todo_complete' CLAUDE.md` returns nothing.
2. ✅ `grep 'mcp__plugin_proj_proj__todo_complete' CLAUDE.md` returns exactly one match (in the rewritten section).
3. ✅ The section's intent (batch call > N sequential calls) is preserved.
4. ✅ Single commit on the feature branch with the message above.

---

## Self-Review Notes

**Spec coverage**: spec's "Architecture" + "Why this rewrite" → Task 1 Step 2's replacement text. Spec's "Testing" (manual verification only) → Task 1 Step 3's grep verifications. Spec's "Non-goals" (other rules untouched, managed CLAUDE.md untouched) → enforced by edit being scoped to lines 47-55.

**Placeholders**: none.

**Type/name consistency**: `mcp__plugin_proj_proj__todo_complete` and `todo_ids` used identically in spec, replacement text, and grep checks.
