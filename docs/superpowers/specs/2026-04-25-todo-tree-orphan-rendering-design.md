# Todo Tree Orphan Rendering — Design Spec

**Date**: 2026-04-25
**Todo**: 733 — `todo_tree: don't flag orphan when group:<id> parent exists but is done/archived`
**Author**: brainstorming session (Raul + Claude Opus 4.7)
**Status**: design approved; awaiting user spec review → writing-plans

---

## Problem statement

`todo_tree` (compact + full modes) buckets a todo with a `group:<id>` tag under a `__orphaned__` header when `<id>` is not present in the active todo set. This is wrong when the parent merely transitioned to archived/done — the parent still EXISTS, just outside the default render window.

Trigger 2026-04-25: added 729-732 (727 follow-ups) tagged `group:727`, then archived 727. `todo_tree` showed all four under `__orphaned__`. Cleaned manually by stripping the tag — but the tag was correct provenance ("this child belonged to group 727"); only the rendering was wrong.

## Goal

Render a child whose parent is archived/done at the top level alongside other un-parented todos. Preserve the `group:<id>` tag for provenance. Reserve the `__orphaned__` bucket for genuinely orphaned children (parent record deleted entirely — does not exist in active OR archive sets).

## Locked constraints (per todo notes + this brainstorm)

1. **Render-side fix only** (option 1 in todo notes). No server-side hook on parent archive. No tag rewrite. No "closed group" concept.
2. **Tag preserved for provenance** — child keeps `group:<id>` tag forever; rendering becomes the smart layer.
3. **`__orphaned__` header hidden when bucket is empty** — if every former-orphan reclassifies to top-level, header omitted entirely (cleaner UX; matches user intent).
4. **Storage backend is SQLite** (corrects stale memory): `load_todos` / `load_archived_todos` are SQL queries against `lib/db.py`. Loading archived for the existence check is one extra SELECT — negligible cost. Even cheaper option: a single `SELECT id` query against UNION of active + archived tables — return existence-only set, no row hydration.

## Non-goals

- Auto-rewrite `group:<id>` → `was-group:<id>` on parent archive (rejected option 2 in todo notes — touches Todoist/Trello label sync, large blast radius).
- Auto-strip `group:<id>` tag on parent archive (rejected option 3 — loses provenance).
- New "closed group" UX concept or section header for archived-parent children.
- Trello sync changes — confirmed independent: each grouped child Trello card carries its own `group:<parent-id>` label; archive of parent does not cascade per [[625-sync-flat-model-alignment]] "Each todo's lifecycle independent of its group siblings."
- Behavior change when `include_done=True` — that mode already loads archived into the active set, so existing parent-in-todo_map check works correctly.

## Architecture

Single function change: `todo_tree` in `plugins/proj/server/server/tools/todos.py` (currently lines 1440-1500ish). The bucketing logic at lines 1467-1477 expands from a 2-way classification (in-todo_map vs not) to a 3-way classification:

| Parent state | Render | Header |
|---|---|---|
| In current `todo_map` (active set) | Under parent (existing) | Parent's title |
| Exists in archived set, not in `todo_map` | Top level (NEW) | None — alongside other un-parented todos |
| Doesn't exist in active OR archived (genuinely deleted) | Under `__orphaned__` (existing) | `__orphaned__` (only when bucket non-empty) |

### Implementation sketch

```python
# After building todo_map for the active set (existing code)

# NEW: load archived todos for parent-existence check ONLY
# (skip if include_done=True — those are already in todo_map)
archived_id_set: set[str] = set()
if not include_done:
    archived_id_set = {t.id for t in storage.load_archived_todos(cfg, name)}

# Reclassify each todo with a group:<id> tag
for t in todos:
    parent_id = parent_id_from_tags(t.tags)
    if parent_id is None:
        continue  # already a root

    if parent_id in todo_map:
        # existing: render under parent (handled in roots construction)
        pass
    elif parent_id in archived_id_set:
        # NEW: archived parent → render at top level (no __orphaned__ bucket)
        roots.append(todo_map[t.id])
    # else: genuinely deleted → falls through to existing __orphaned__ logic

# Existing __orphaned__ logic stays, but now only catches genuine deletions:
orphaned = [
    todo_map[t.id]
    for t in todos
    if (pid := parent_id_from_tags(t.tags)) is not None
    and pid not in todo_map
    and pid not in archived_id_set  # NEW: exclude archived
]
if not include_done:
    orphaned = [o for o in orphaned if _filter_tree_node(o) is not None]
if orphaned:  # existing: header hidden when bucket empty (no change needed)
    roots.append({"id": "__orphaned__", "title": "⚠️ Orphaned", "_children": orphaned})
```

The exact integration with the existing `roots` construction (line 1464) needs care: the existing `roots = [todo_map[t.id] for t in todos if not parent_id_from_tags(t.tags)]` only picks tagless roots. The new logic must extend this to also append archived-parent children. Best done by computing the archived-parent set up front + filtering it into `roots` alongside the tagless ones.

### Cleaner alternative: single SQL query

If the existence check becomes a hot path (it won't, but for correctness clarity), a single `SELECT id FROM todos UNION SELECT id FROM archived_todos WHERE id IN (?, ?, ...)` returning matched parent IDs avoids loading two full lists. Out of scope for v1; revisit if profiling shows cost.

## Compact mode

`compact=True` path (line 1484+) renders one line per todo via `_compact_tree_line`. Same logic applies — the change is upstream of compact rendering, in the tree-construction step. Compact-vs-full doesn't fork.

## Tests

`plugins/proj/server/tests/test_todos.py` (or wherever `todo_tree` tests live):

1. **Regression**: active parent + child with `group:<parent>` → child under parent (existing behavior preserved).
2. **NEW**: archived parent + child with `group:<archived>` + `include_done=False` → child at top level; NO `__orphaned__` header.
3. **Regression**: deleted parent (no record in active or archived) + child with `group:<deleted>` → child under `__orphaned__` header.
4. **NEW**: mix — one child w/ archived parent + one child w/ deleted parent → archived child top-level; deleted child under `__orphaned__`; bucket has 1 entry.
5. **NEW**: archived parent + child w/ `group:<archived>` + `include_done=True` → child under parent in tree (regression: behavior unchanged when archived loaded into todo_map).
6. **NEW**: archived parent + child + `compact=True` → compact line for child at top level, NO `__orphaned__` line.
7. **Header-hidden case**: ALL children have archived parents (no genuine orphans) → `__orphaned__` header NOT rendered (no empty section).

Test fixtures: arrange via direct `storage.save_todos` + `storage.save_archived_todos_append` — no test for hook chains needed (this is render-only).

## Risks

| Risk | Mitigation |
|---|---|
| Children with archived parents flood top level → visual noise when batches archive | Acceptable per locked decision; alternative (synthetic "Archived parent" header) was rejected as out of scope. User can split by reading the `group:*` tag. |
| Child's `group:<id>` references a parent that exists in BOTH active AND archived (edge case: parent restored from archive) | First match wins (active set). Code naturally handles this: `if parent_id in todo_map` is checked first. |
| Performance regression on huge archives | Negligible — one extra SQL query returning IDs only. If profiling later shows cost, switch to single UNION query (architecture sketch). |
| Future change to flat-model parent resolution drifts from this fix | Cross-ref [[flat-todo-model]] wiki page in code comments. Add wiki ingest after ship (todo 733 follow-up). |

## Skill structure (pure code change, no skill artifacts)

- File: `plugins/proj/server/server/tools/todos.py` (1 fn change)
- Tests: `plugins/proj/server/tests/test_todos.py` (or sibling) — 7 test cases (mix new + regression)
- No new MCP tool. No new SKILL. No managed CLAUDE.md change. No wiki page rename.

## Wiki

After ship: ingest fix details into wiki via `/wiki:ingest` so future `/wiki:query "todo_tree orphan archived parent"` returns a direct hit. Topic page slug suggestion: `todo-tree-orphan-rendering` under `concepts` or merge into existing `[[flat-todo-model]]` page as a new section.

## Validation

Manual repro: re-trigger the 2026-04-25 condition (add child w/ `group:<id>`, archive parent, run `todo_tree`) → verify child at top level + no `__orphaned__` header. Plus the 7 automated tests above.

## Cross-references

- Wiki: [[flat-todo-model]] (flat-model parent resolution; `group:*` tag is the parent pointer post-migration)
- Wiki: [[todo-list-compact-default]] (compact rendering of `todo_tree`)
- Wiki: [[625-sync-flat-model-alignment]] (Trello sync independence — confirms no cross-system drift from this fix)
- Source: `plugins/proj/server/server/tools/todos.py:1440-1500` (current `todo_tree` impl)
- Source: `plugins/proj/server/server/lib/sql_todos.py` (storage backend — SQL, not YAML; corrects stale MEMORY.md note)
- Trigger session: 2026-04-25 (todo 727 archive cascade; this session's todo 733 brainstorm)
- Followup: ingest fix into wiki post-ship per managed rule 25
- Sibling todo 739 (just created) — debug why managed rule 25 (research synthesis) gets skipped during brainstorms
