# 636 Phase 2 — Flat-Model Cleanup Design Spec

**Todo:** 636 Phase 2 (follow-up to Phase 1, which shipped 2026-04-17)
**Status:** Draft
**Date:** 2026-04-17
**Predicates:** 624 + 636 Phase 1 both landed on dev.

## 1. Context

Phase 1 (636) delivered the installer wizard migration that flattens nested `parent`/`children` todos into flat top-level todos tagged `group:<parent-id>`. Phase 1 kept dual-path support in the server: `_todo_hook_fields` resolves parents from either the `group:` tag OR the legacy `todo.parent` field. `_batch_add_children` honors both modes via a `flat` kwarg. Phase 2 is the dead-code retirement — once projects have migrated, the legacy path is noise.

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|---|---|
| 1 | Scope boundary | Narrow: server-side cleanup only. Full-sync code audit stays separate (todo 625). |
| 2 | `/proj:flatten-children` skill | Retire entirely. Wizard (Phase 1) is the canonical migration path. |
| 3 | `todo_add_child` hook triggers | Delete orphan entries from todoist/trello default-hooks.yaml. Never fired — no tool of that trigger name exists. |
| 4 | `Todo` dataclass fields | Delete `parent`, `children`, `next_child_id` entirely. |
| 5 | v1 project handling | Raise `LegacyProjectError` with actionable message pointing at `cpm-install --migrate-flat`. Migration is the wizard's job. |

## 3. Architecture

Seven small cleanup concerns:

### 3.1 `Todo` dataclass + SQL schema

Drop these fields from `plugins/proj/server/server/lib/models.py::Todo`:
- `parent: str | None`
- `children: list[str]`
- `next_child_id: int`

Update `plugins/proj/server/server/lib/sql_todos.py` + `sql_archive.py`:
- Remove those columns from INSERT / SELECT column lists
- Schema on v2 projects already has them dropped by 636 Phase 1's `flatten_todos_sql` — nothing more to do at the SQL level. For legacy v1 projects that never migrated, the new code would fail trying to INSERT against an old schema → `LegacyProjectError` catches that earlier.

### 3.2 Parent resolution

`plugins/proj/server/server/tools/todos.py`:

Simplify `_resolve_parent_for_hooks(todo, todos)`:
```python
def _resolve_parent_for_hooks(todo: Todo, todos: list[Todo]) -> ParentLinks:
    """Resolve parent integration IDs for hook dispatch via group:<id> tag."""
    parent_id = _parent_id_from_tag(todo.tags)
    if not parent_id:
        return ParentLinks()
    parent = next((t for t in todos if t.id == parent_id), None)
    if parent is None:
        return ParentLinks()
    return ParentLinks(
        todoist_task_id=parent.todoist_task_id,
        trello_card_id=parent.trello_card_id,
        trello_checklist_id=parent.trello_checklist_id,
        jira_issue_key=parent.jira_issue_key,
    )
```

The `_parent_id_from_tag(todo.tags) or todo.parent` resolution becomes tag-only. `ParentLinks` + `_parent_id_from_tag` are unchanged.

### 3.3 `todo_add` + `_batch_add_children`

Remove the entire `_enforce_flat_args` helper + `_FLAT_MODE_ERROR` constant + the `schema_version.flat_only`-gated call site in `todo_add`. They become unreachable:
- `parent=X, title=...` (single-child nested) is already rejected for v2 projects
- After Phase 2, every project is v2 (runtime guard from §3.4 enforces this)
- The enforcement gate is no longer meaningful — there's no nested path to allow

`_batch_add_children`:
- Drop the `flat: bool = False` kwarg
- Always auto-tag children with `group:<parent.id>` (the former `flat=True` branch)
- Remove all legacy-parent-field writes from the child-construction loop
- `parent.children.append(child.id)` block is already conditionally skipped when `flat=True`; in Phase 2 it's removed entirely

Callers that pass `parent=X, children=[...]` on `todo_add` still work — they go through the batch path which now always auto-tags.

### 3.4 Runtime guard for v1 projects

New function in `plugins/proj/server/server/lib/schema_version.py`:

```python
class LegacyProjectError(RuntimeError):
    """Raised when a project is still on the nested (pre-flat-model) schema."""


def require_flat(cfg: ProjConfig, project_name: str) -> None:
    if not flat_only(cfg, project_name):
        raise LegacyProjectError(
            f"Project {project_name!r} is still on the nested todo schema "
            f"(schema_version < {TARGET}). Run `cpm-install --migrate-flat` "
            f"to upgrade this project before using todo tools."
        )
```

Call `require_flat` from the entry point of every read/write storage function that touches todos:
- `storage.load_todos(cfg, project_name)` — first line
- `storage.save_todos(cfg, project_name, todos)` — first line
- `storage.load_archive(cfg, project_name)` — first line
- `storage.save_archive(cfg, project_name, archive)` — first line

This ensures any tool (todo_add, todo_update, todo_complete, etc.) that goes through storage surfaces the error with the actionable message. No need to sprinkle guards across every MCP tool individually.

### 3.5 `/proj:flatten-children` skill retirement

Delete `plugins/proj/skills/flatten-children/` entirely. Update:
- `README.md` — remove any skill listing entry
- Skill index files that enumerate skills (if any)
- Any cross-references from other skills

The wizard's Phase 1 migration is the replacement.

### 3.6 Dead hook entries

Delete from `plugins/todoist/.claude-plugin/default-hooks.yaml`:
- `todoist-on-todo-add-child`

Delete from `plugins/trello/.claude-plugin/default-hooks.yaml`:
- `trello-on-todo-add-child`
- `trello-on-todo-batch-add-children`

These triggered on MCP tools (`todo_add_child`, `todo_batch_add_children`) that were never created. 623.8 findings documented them as dead. Phase 2 removes them.

### 3.7 Test cleanup

- Tests that constructed `Todo(id=..., parent=..., children=...)` → drop those kwargs
- Tests specific to the Phase 1 enforcement gate behavior (test_todo_add_schema_version_gate.py) — obsolete. Replace with a single test verifying `LegacyProjectError` raises for v1 projects.
- `test_resolve_parent_for_hooks::test_resolve_falls_back_to_parent_field` — remove (legacy path gone)
- `test_resolve_parent_for_hooks::test_hook_fields_legacy_nested_child_still_works` — remove
- `test_resolve_parent_for_hooks::test_resolve_uses_group_tag_over_parent_field` — simplify to "resolve uses group tag" (no more "over parent field" comparison)
- E2E tests from 636 Phase 1 (happy path, rollback, etc.) all use v2 schema — unchanged

## 4. Data flow (post-Phase-2)

```
todo_add(title, tags=["group:1"])
  → state.resolve_project → cfg, name
  → storage.load_todos(cfg, name)
      → schema_version.require_flat(cfg, name)   # raises LegacyProjectError if v1
      → sql_todos.load_todos(cfg, name)          # no parent/children cols
      → returns list[Todo]  # Todo has no parent/children/next_child_id fields
  → build new Todo (tags include "group:1")
  → storage.save_todos(cfg, name, todos)
      → require_flat  (no-op if cached — but we don't cache per 624 design)
      → sql_todos.save_todos                      # no parent/children cols
  → hook dispatch
      → _todo_hook_fields(todo, meta, name, todos=..., cfg=...)
          → _resolve_parent_for_hooks  # tag-only resolution
          → emit parent_todoist_task_id / parent_jira_issue_key etc.
          → emit synced_tags
      → router fires todoist-on-todo-add etc.
```

## 5. Migration / deployment considerations

- Any dev environment running this branch MUST run the Phase 1 wizard first (`cpm-install --migrate-flat`) OR accept that v1 projects raise `LegacyProjectError` on first use.
- The error message tells users exactly what to do; this is not a silent failure.
- CI runners create ephemeral v2 projects in tests — not affected.
- Existing cpm tracking dir (the dev environment's own `~/projects/tracking/claude-project-manager/`) is currently v1. A one-off migration is needed before Phase 2 merges.

## 6. Testing strategy

- **Unit (10-ish new/changed tests):**
  - `test_schema_version_require_flat.py` — `LegacyProjectError` raises for v1, passes for v2
  - `test_todo_hook_fields_flat.py` — drop 2 legacy tests, simplify 1 (3 fewer tests net)
  - `test_todo_add_schema_version_gate.py` — DELETE file (obsolete gate)
  - `test_resolve_parent_for_hooks` cases adjusted per §3.7
- **Regression:** full proj + router + trello + jira + todoist + worktree + installer suites should pass
- **Dataclass constructor changes** will surface any test that passes `parent=`/`children=` → update those
- **Coverage target:** ≥79.5% line coverage on proj plugin (unchanged)

## 7. Out of scope

- Todo 625 (Trello + Jira full-sync audit for flat model) — deferred, will subsume this if done next
- Todo 637 (Jira sync architecture revisit) — deferred
- Any installer changes — Phase 1's wizard is the migration path
- Renaming `parent=` kwarg on `todo_add` — stays as-is (semantic is now "auto-tag batch children with group:<parent>")

## 8. Risks

- **Dev environment v1 projects:** before merging, devs must run the migration. PR description + release notes must flag this.
- **Unlabeled tests:** tests that construct `Todo(parent=...)` directly via positional or kwarg will fail at dataclass init with `TypeError: unexpected keyword argument 'parent'`. Systematic grep + update needed.
- **Sync plugins:** `plugins/todoist/server/server/tools/todoist_sync.py` and similar may reference `.parent` on todos. These fall under todo 625, but any that fail hard after Phase 2 need at minimum a clear error or attribute shim. Spot-check during implementation.

## 9. Follow-up todos (filed post-Phase-2)

- 625 remains pending — full-sync code audit for flat model
- No new follow-ups anticipated from Phase 2 itself
