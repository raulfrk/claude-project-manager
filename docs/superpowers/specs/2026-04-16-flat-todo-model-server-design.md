# Flat-Todo Model — Server + Hook Changes (Todo 624) Design Spec

**Todo:** 624 (unblocks 636 Phase 1)
**Status:** Draft
**Date:** 2026-04-16

## 1. Context

The project is migrating from a nested (`parent`/`children` field) todo model to a flat model where children become top-level todos carrying a `group:<parent-id>` tag. Todo 623.8 verified the behavior of the existing hook dispatch against this new shape and found that **flat todos currently break integration sync for Todoist parent nesting, Jira Epic Link, and Trello parent-card relationships** because `_todo_hook_fields` only resolves a parent from `todo.parent`, not from a `group:` tag.

Todo 624's job is to close those gaps inside the proj MCP server and the integration hook configs, plus introduce a `schema_version`-gated guard so that post-migration projects can't regress into nested state.

**Todo 636 Phase 1 — the installer migration — is blocked on this spec landing.** 636's design already assumes the changes here are in place.

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Flat-only enforcement trigger | Gated by `schema_version >= 2` in each project's `proj.yaml`. Pre-migration behavior identical to today. |
| 2 | Jira `parent_key` bug fix | Fix as part of 624: reference new `parent_jira_issue_key` field; condition on `omit_if_empty: true`. |
| 3 | `group:*` tags in remote labels | Emit new `synced_tags` field stripped of `group:*` prefix. Todoist/Jira hooks use `synced_tags` for labels. Raw `tags` preserved for local display. |
| 4 | `todo_add_flat_batch` MCP tool | Not adding a new tool. Reuse existing `todo_add(title="", parent=<id>, children=[...])` children-only mode. Post-enforcement, batch path auto-tags children with `group:<parent>` instead of setting `parent` field. |

## 3. Architecture

Four small concerns, each a separate commit inside this PR.

**Files touched:**

| File | Change |
|------|--------|
| `plugins/proj/server/server/tools/todos.py` | Extract `_resolve_parent_for_hooks` helper; emit `synced_tags` + `parent_jira_issue_key`; enforcement guard in `todo_add` + `_batch_add_children` + `todo_add_child`. |
| `plugins/proj/server/server/lib/schema_version.py` | **NEW** — `current()`, `flat_only()`, `TARGET = 2`. |
| `plugins/jira/.claude-plugin/default-hooks.yaml` | `labels: "${synced_tags}"`; `parent_key` uses `parent_jira_issue_key` with `omit_if_empty: true`. |
| `plugins/todoist/.claude-plugin/default-hooks.yaml` | `labels: "${synced_tags}"`. |
| `plugins/trello/.claude-plugin/default-hooks.yaml` | `labels: "${synced_tags}"` if any hook reads `tags` today. |
| `plugins/router/server/server/lib/template.py` | Add `omit_if_empty: true` support in `param_mapping` DSL (confirm during implementation; may already exist). |

## 4. Group-tag parent resolution in `_todo_hook_fields`

New helper in `todos.py`:

```python
@dataclass(frozen=True)
class ParentLinks:
    todoist_task_id: str | None = None
    trello_card_id: str | None = None
    trello_checklist_id: str | None = None
    jira_issue_key: str | None = None


_GROUP_TAG_RE = re.compile(r"^group:(?P<id>.+)$")


def _parent_id_from_tag(tags: list[str]) -> str | None:
    for tag in tags:
        m = _GROUP_TAG_RE.match(tag)
        if m:
            return m.group("id")
    return None


def _resolve_parent_for_hooks(todo: Todo, todos: list[Todo]) -> ParentLinks:
    parent_id = _parent_id_from_tag(todo.tags) or todo.parent
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

**Resolution order:** `group:<id>` tag wins over `todo.parent` when both are present. Post-migration, only the tag path has data.

**Tag parsing:** first `group:*` tag wins. If multiple exist, a DEBUG log records the ambiguity. We deliberately don't enforce single-group at the schema level — tags stay free-form metadata.

**`_todo_hook_fields` call site** replaces the current lines 172–180 with:

```python
parent_links = _resolve_parent_for_hooks(todo, todos)
if parent_links.todoist_task_id:
    fields["parent_todoist_task_id"] = parent_links.todoist_task_id
if parent_links.trello_card_id:
    fields["parent_trello_card_id"] = parent_links.trello_card_id
if parent_links.trello_checklist_id:
    fields["parent_trello_checklist_id"] = parent_links.trello_checklist_id
if parent_links.jira_issue_key:
    fields["parent_jira_issue_key"] = parent_links.jira_issue_key  # NEW
```

**New field:** `parent_jira_issue_key`. Previously not injected at all; consumed by the Jira hook fix in §6.

**Unchanged:** `_todo_hook_fields` signature, return shape, and all other field keys. Existing hooks that read only `parent_todoist_task_id` / `parent_trello_card_id` continue to work for both flat and legacy data.

## 5. `synced_tags` field

Same function, new emitted field:

```python
fields["synced_tags"] = [t for t in todo.tags if not t.startswith("group:")]
```

**Additive** — the raw `tags` field is unchanged. Skills, local display, and any hook that wants the raw tag list still read `tags`. Remote-facing hooks switch to `synced_tags`.

**Hook config flips** (all in the same commit as the `_todo_hook_fields` change):

| File | Hook | Change |
|------|------|--------|
| `plugins/todoist/.claude-plugin/default-hooks.yaml` | `todoist-on-todo-add` | `labels: "${synced_tags}"` |
| `plugins/jira/.claude-plugin/default-hooks.yaml` | `jira-on-todo-add` | `labels: "${synced_tags}"` |
| `plugins/trello/.claude-plugin/default-hooks.yaml` | any hook that reads `tags` | `labels: "${synced_tags}"` (if applicable; the card-creation hook doesn't send labels today, so this may only affect `trello-full-sync` paths) |

**Edge cases:**
- all tags are `group:*` → `synced_tags=[]`; remote APIs accept an empty labels list
- empty-vs-absent distinction: not needed; both behave the same at the API level
- manual / `auto-added` / `flat-model` / user-authored tags pass through intact — only the `group:` prefix is stripped

## 6. Jira hook `parent_key` fix

Two changes on the `jira-on-todo-add` hook in `plugins/jira/.claude-plugin/default-hooks.yaml`:

```yaml
- id: jira-on-todo-add
  trigger_tool: todo_add
  target_server: jira
  target_tool: jira_create_issue
  condition: "sync.jira.enabled and sync.jira.auto_sync and project.jira_issue_key"
  param_mapping:
    project_key: "${jira_project_key}"
    summary: "${title}"
    description: "${notes}"
    priority: "${priority}"
    labels: "${synced_tags}"
    parent_key:
      value: "${parent_jira_issue_key}"
      omit_if_empty: true
```

**Before → after:**
- `parent_key: "${jira_issue_key}"` (the new todo's own, empty, Jira key) → `parent_key: "${parent_jira_issue_key}"` (the parent's Jira key, or absent)
- Added `omit_if_empty: true` so top-level todos (no parent) don't send `parent_key=""` to the Jira API

**Result:**

| Todo shape | Jira call |
|------------|-----------|
| Top-level flat todo (no parent) | `jira_create_issue(...)` — no `parent_key` |
| Flat child with `group:<epic-key-todo-id>` | `jira_create_issue(..., parent_key=<epic jira key>)` |
| Legacy nested child (`todo.parent=<id>`) | `jira_create_issue(..., parent_key=<parent jira key>)` — backward compat |
| Flat child whose parent is not synced to Jira | `jira_create_issue(...)` — no `parent_key`; next `/proj:jira-sync` reconciles |

**Router DSL prerequisite:** `omit_if_empty: true` support in `plugins/router/server/server/lib/template.py`. During implementation, check whether the DSL already accepts the `{value, omit_if_empty}` object form. If not, extend it: a one-line check in the param-resolution loop that skips the key when its resolved value is falsy. If DSL extension is out-of-scope for this PR, fallback is to split the hook into two near-duplicate entries with different conditions — more YAML, no code change — but the DSL extension is preferred.

## 7. `schema_version`-gated flat-only enforcement

### 7.1 New module

`plugins/proj/server/server/lib/schema_version.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from . import storage

if TYPE_CHECKING:
    from .models import ProjConfig

TARGET = 2


def current(cfg: ProjConfig, project_name: str) -> int:
    """Return the project's schema_version. Missing field → 1."""
    meta = storage.load_project_meta(cfg, project_name)
    v = meta.get("schema_version")
    try:
        return int(v) if v is not None else 1
    except (TypeError, ValueError):
        return 1


def flat_only(cfg: ProjConfig, project_name: str) -> bool:
    return current(cfg, project_name) >= TARGET
```

No caching — `todo_add` is not a hot path and values change when 636 migration runs.

### 7.2 Enforcement rules

`todo_add` acquires the gate at entry:

```python
def todo_add(..., parent=None, children="[]", ...):
    cfg = require_config()
    project = _resolve_project_name(cfg, project_name)

    children_list = json.loads(children) if children else []
    if schema_version.flat_only(cfg, project):
        _enforce_flat_args(title=title, parent=parent, children=children_list)
    # ... existing flow ...
```

Truth table (post-enforcement):

| `title` | `parent=` | `children=` | Verdict |
|---------|-----------|-------------|---------|
| non-empty | None | empty | **allowed** — creates flat top-level todo |
| non-empty | non-empty | empty | **rejected** — use `tags=["group:<id>"]` for single child |
| empty | non-empty | non-empty | **allowed** — canonical flat batch path |
| non-empty | any | non-empty | **rejected** — use batch or single path, not both |
| empty | None | any | **rejected** today regardless — nothing to create |

Error message:

```
todo_add: nested mode disabled (project schema_version >= 2).
  • single child:  todo_add(title="...", tags=["group:<parent-id>"])
  • batch:         todo_add(title="", parent="<parent-id>", children=[...])
```

### 7.3 Batch path behavior change

`_batch_add_children` gets one-line change when `flat_only=True`: instead of setting `child.parent = parent_id`, it appends `f"group:{parent_id}"` to each child's `tags` (dedup-aware, case-sensitive). The `parent` field on the created todo is never set under this mode.

```python
def _batch_add_children(parent_id, specs, *, flat: bool):
    created = []
    for spec in specs:
        if flat:
            tags = list(spec.get("tags", []))
            group_tag = f"group:{parent_id}"
            if group_tag not in tags:
                tags.append(group_tag)
            spec = {**spec, "tags": tags}
            spec.pop("parent", None)
        else:
            spec = {**spec, "parent": parent_id}
        created.append(_create_one(spec))
    return created
```

Pre-enforcement behavior (flat=False) is untouched.

### 7.4 `todo_add_child`

Same guard. When `flat_only` is True, `todo_add_child` rejects with the same actionable error pointing to `todo_add(tags=["group:<parent>"])`. 624 does not delete the tool; Phase 2 may reduce it to a thin wrapper or remove it.

### 7.5 Legacy behavior (schema_version < 2)

All existing behavior unchanged. Guards are no-ops. Test matrix exercises both modes.

## 8. Testing

Four unit-test files + one e2e file, ~30 new tests total.

### 8.1 Parent resolution — `tests/proj/test_todo_hook_fields_flat.py`

- `test_parent_id_from_tag_finds_group`
- `test_parent_id_from_tag_no_match`
- `test_parent_id_from_tag_multiple_uses_first` (+ DEBUG log captured)
- `test_parent_id_from_tag_weird_values` — `group:`, `group:foo.bar`, `group: leading_space`
- `test_resolve_prefers_group_tag_over_parent_field`
- `test_resolve_falls_back_to_parent_field`
- `test_resolve_missing_parent_returns_empty`
- `test_resolve_empty_when_parent_has_no_integrations`
- `test_hook_fields_flat_child_injects_todoist_id`
- `test_hook_fields_flat_child_injects_jira_key`
- `test_hook_fields_flat_child_injects_trello_card_id`
- `test_hook_fields_top_level_has_no_parent_fields`
- `test_hook_fields_legacy_nested_child_still_works`

### 8.2 `synced_tags` — `tests/proj/test_todo_hook_fields_synced_tags.py`

- `test_synced_tags_strips_group_prefix`
- `test_synced_tags_preserves_order`
- `test_synced_tags_empty_when_only_group_tags`
- `test_synced_tags_unchanged_when_no_group_prefix`
- `test_tags_field_still_includes_group_tag`

### 8.3 Hook config smoke — `tests/proj/test_default_hooks_refs.py`

YAML parse + key assertions (catch typos in CI):

- `test_todoist_hook_references_synced_tags`
- `test_jira_hook_references_synced_tags`
- `test_jira_hook_parent_key_uses_parent_jira_issue_key`
- `test_jira_hook_parent_key_has_omit_if_empty_true`
- `test_jira_hook_condition_unchanged`

### 8.4 Enforcement gate — `tests/proj/test_todo_add_schema_version_gate.py`

Parameterized across `schema_version=1` (gate off) and `schema_version=2` (gate on):

- `test_flat_mode_rejects_single_child_with_parent`
- `test_flat_mode_allows_tags_group_syntax`
- `test_flat_mode_batch_path_auto_tags_children`
- `test_flat_mode_batch_path_dedups_existing_group_tag`
- `test_flat_mode_rejects_single_child_via_todo_add_child_tool`
- `test_legacy_mode_all_cases_pass` (regression guard)
- `test_gate_reads_schema_version_fresh_each_call` (no caching regression)

### 8.5 End-to-end via hook dispatch — `tests/proj/test_todo_add_e2e_hooks.py`

respx-mocked integration tests exercising the full `todo_add → hook → target-tool` chain:

- `test_e2e_flat_child_fires_todoist_hook_with_parent_id` — asserts Todoist request carries `parentId=<parent todoist_task_id>` and `labels=[]` (no `group:*` pollution)
- `test_e2e_flat_child_fires_jira_hook_with_epic_parent_key`
- `test_e2e_top_level_flat_todo_fires_jira_hook_without_parent_key`

### 8.6 Coverage

≥ 79.5% line coverage on the proj plugin (matches existing convention). No snapshot tests required.

## 9. Out of scope

- **Deletion of `parent` / `children` fields from storage.** 636 migration drops them; 624 only teaches the server to honor `group:<id>` tags alongside the legacy field.
- **`todo_add_child` MCP tool retirement.** 624 gates it but does not remove it.
- **Full-sync code (`/proj:trello-sync`, `/proj:jira-sync`) audit for parent/child assumptions.** Tracked separately by 637 (Jira sync architecture revisit) and 636 Phase 2.
- **Hook DSL beyond `omit_if_empty`.** No broader DSL refactoring in this PR.
- **Retrofitting old Todoist tasks that already sync with `group:*` labels.** Next full sync reconciles.

## 10. Follow-up todos

- **636 Phase 1** (blocked by 624) — installer wizard migration.
- **637** — Jira sync architecture revisit (may subsume `omit_if_empty` extension if DSL work grows).
- **636 Phase 2** (filed post-636 Phase 1) — hook/sync code cleanup after migration lands.
