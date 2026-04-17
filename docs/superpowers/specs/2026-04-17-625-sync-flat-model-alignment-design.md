# 625 — Trello + Jira Sync Flat-Model Alignment Design Spec

**Todo:** 625
**Status:** Draft
**Date:** 2026-04-17
**Predicates:** 624 + 636 Phase 1 + 636 Phase 2 + 647 all landed on dev.

## 1. Context

After 624 + 636, the local model is flat (`group:<parent-id>` tag). Sync code paths (trello_sync / trello_full_sync / jira_sync / jira_full_sync) were written for the nested model and haven't been audited. Survey on 2026-04-17 found:

- **Bug A (trello_full_sync pull broken):** `_sync_single_project` fetches checklists and passes `{"checklists": [...]}` to `compute_diff`, but `compute_diff` reads `trello_data.get("cards", [])`. Result: every sync sees zero cards and proposes re-creating every local todo's card.
- **Bug B (jira_sync crashes on sub-tasks):** `apply_mapping` creates `Todo(parent=..., children=...)` — post-Phase-2 these kwargs don't exist on the dataclass. Jira pull crashes on any project with sub-tasks.
- **Missing feature:** group relationships are invisible in both Trello and Jira. No label, no hierarchy, no cross-reference.
- **Jira import rule tree:** needs to honor the flat model + the user's product requirements about what Jira issues become local projects vs todos.

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Scope | Bug fixes + Trello group labels + Jira import rule tree in one PR. |
| 2 | Trello representation of group children | Each grouped child card gets a Trello label named `group:<parent-id>`. Label created on-demand with stable color. |
| 3 | Jira push | Not in scope — Jira is pull-only. |
| 4 | Jira import rules | See §5 — rule tree with Epic=project / Task=project-or-todo-in-epic / Sub-task=todo-or-orphan-project. |
| 5 | Completion cascade | No cascade. Each todo's lifecycle independent of its group siblings. |
| 6 | Epic owner definition | `assignee == current_user` (matches `jira_get_user_issues` filter). |
| 7 | Epic scope | Only tasks assigned to me are imported into my epic's project. Delegated-out tasks stay in Jira, invisible locally. |
| 8 | Orphan sub-task | Sub-task whose parent task is not mine AND grandparent epic (if any) is not mine — becomes its own local project (empty placeholder). |

## 3. Architecture

**Files touched:**

```
plugins/proj/server/server/tools/
  trello_sync.py           # Bug A fix (card-fetch alignment); group labels in compute_diff
  trello_full_sync.py      # Bug A fix (fetch cards not checklists)
  jira_sync.py             # Bug B fix (Todo kwargs); rewrite apply_mapping per rule tree
  jira_full_sync.py        # Bug B fix if it re-exposes the bug path

plugins/proj/server/tests/
  test_trello_full_sync_fetch.py          # NEW — Bug A regression
  test_trello_group_labels.py             # NEW — label feature
  test_jira_apply_mapping_flat.py         # NEW — Bug B regression
  test_jira_import_rules.py               # NEW — rule tree coverage (~10 tests)
```

No new modules. All changes land in existing sync tool files.

## 4. Trello fixes + group labels (Bug A + feature)

### 4.1 Bug A fix

`trello_full_sync._sync_single_project` — replace the checklist-based fetch with a card-level fetch.

Current broken pattern:
```python
cl = get_card_checklists(project_card_id)
trello_card_json = {"checklists": [...]}
diff = compute_diff(todos, trello_card_json, ...)  # diff sees empty cards[]
```

New pattern:
```python
cards = []
for list_id in [tasks_list_id, done_list_id]:
    cards.extend(get_cards_by_list_id(list_id))
lists = get_lists(board_id)
project_card = get_card(project_card_id)
trello_data = {"cards": cards, "lists": lists, "project_card": project_card}
diff = compute_diff(todos, trello_data, ...)
```

Delete the checklist-walk code in `_sync_single_project` — it was a dead limb from the pre-card-per-todo era.

### 4.2 Group label feature

In `trello_sync.compute_diff`, for each card being created or updated:

```python
group_tags = [t for t in todo.tags if t.startswith("group:")]
for tag in group_tags:
    # tag = "group:475"
    label_name = tag
    # Ensure label exists on board; create if missing.
    label_id = _ensure_group_label(board_id, label_name)
    if label_id not in card.idLabels:
        push_label_attach.append({"card_id": card.id, "label_id": label_id})
```

`_ensure_group_label(board_id, name)`:
- Calls `get_labels(board_id)`, checks for exact name match.
- If missing, calls `create_label(board_id, name, color=_stable_color_for(name))`.
- Caches result for this sync run.

`_stable_color_for(name)` — deterministic color from the tag:
```python
TRELLO_LABEL_COLORS = ["green", "yellow", "orange", "red", "purple",
                       "blue", "sky", "lime", "pink", "black"]

def _stable_color_for(tag: str) -> str:
    # Use zlib.crc32 for stability across Python versions
    idx = zlib.crc32(tag.encode()) % len(TRELLO_LABEL_COLORS)
    return TRELLO_LABEL_COLORS[idx]
```

### 4.3 Pull path (Trello → local group tag)

When a Trello card has a `group:<id>` label, on pull sync the corresponding local todo's tags should include that tag. If the user removes the label in Trello, the next pull strips the tag locally. Specifically:

In `compute_diff`'s pull direction, compute `desired_tags = local_todo.tags minus group:* + [group-label-names from card]`. If `desired_tags != local_todo.tags`, emit `pull_update_tags` action.

## 5. Jira fixes + import rule tree (Bug B + feature)

### 5.1 Bug B fix

`apply_mapping` — replace nested-Todo construction with flat + group tag. Current (broken):

```python
st_todo = Todo(
    id=next_id(),
    title=subtask.summary,
    parent=parent_todo.id,              # field gone
    children=[],                        # field gone
    ...
)
parent_todo.children.append(st_todo.id)  # field gone
```

New:

```python
st_todo = Todo(
    id=next_id(),
    title=subtask.summary,
    tags=list(subtask_tags) + [f"group:{parent_todo.id}"],
    ...
)
todos.append(st_todo)
```

No mutation of `parent_todo`. The `group:<parent_todo.id>` tag on the sub-task is the sole hierarchy marker.

### 5.2 Import rule tree

Replaces the existing hierarchy logic in `apply_mapping` / `proj_jira_map`.

```python
def import_jira_issues(cfg, current_user):
    # Pass 1: identify epics I'm assigned to
    my_issues = jira_get_user_issues(assignee=current_user)
    my_epic_keys = {iss.key for iss in my_issues if iss.type == "Epic"}

    # Pass 2: assemble the mapping
    for issue in my_issues:
        if issue.type == "Epic":
            _import_epic(cfg, issue, current_user)
        elif issue.type == "Task":
            if issue.epic_link and issue.epic_link in my_epic_keys:
                continue  # handled via Rule 1 when the epic was processed
            _import_task_as_project(cfg, issue, current_user)
        elif issue.type == "Sub-task":
            parent = issue.parent_task
            parent_mine = parent and parent.assignee == current_user
            epic_mine = parent and parent.epic_link in my_epic_keys
            if parent_mine or epic_mine:
                continue  # already wired via parent's rule
            _import_orphan_subtask(cfg, issue, current_user)


def _import_epic(cfg, epic, current_user):
    project = ensure_project(cfg, name=f"epic:{epic.key}", source=epic)
    for task in jira_get_epic_issues(epic.key):
        if task.assignee != current_user:
            continue  # per decision 7: only my tasks
        task_todo = ensure_todo(cfg, project, source=task)
        for subtask in task.subtasks:
            if subtask.assignee != current_user:
                continue
            ensure_todo(cfg, project, source=subtask,
                        extra_tags=[f"group:{task_todo.id}"])


def _import_task_as_project(cfg, task, current_user):
    project = ensure_project(cfg, name=f"task:{task.key}", source=task)
    for subtask in task.subtasks:
        if subtask.assignee != current_user:
            continue
        ensure_todo(cfg, project, source=subtask)


def _import_orphan_subtask(cfg, subtask, current_user):
    # Orphan: sub-task whose ancestors are not mine. Becomes a placeholder project.
    ensure_project(cfg, name=f"task:{subtask.key}", source=subtask)
    # Project has zero todos — contains metadata about the sub-task only.
```

### 5.3 Project naming

- Epic-as-project: `epic:<epic.key>` (e.g. `epic:CPM-100`)
- Task-as-project: `task:<task.key>` (e.g. `task:CPM-50`)
- Orphan sub-task as project: `task:<subtask.key>` (key-based, same schema)

Naming is stable across syncs: re-running the importer updates the project in place rather than creating duplicates. `ensure_project` is idempotent on the name key.

### 5.4 Dedup across passes

The `my_epic_keys` set + epic-link skip in the Task branch ensures a task linked to my epic doesn't get double-processed. The sub-task `parent_mine or epic_mine` check ensures sub-tasks handled via their parent's branch don't get re-processed as orphans.

### 5.5 Deletion / archival

When a Jira issue I was assigned to is reassigned away from me (or deleted), the importer sees it missing from `my_issues`. Local project / todo lifecycle:

- **Orphan sub-task project** (empty container): if the sub-task is no longer mine, delete the local project (`project_archive`).
- **Task-as-project**: if task is reassigned, keep the project + its existing todos (user may still want to reference) but stop syncing updates; mark the project as `jira_detached=true`.
- **Epic-as-project**: same treatment — keep, mark detached.

Detachment preserves user work history; deletion of orphan-placeholder projects cleans up empty shells.

## 6. Testing strategy

### 6.1 Unit tests

**`test_trello_full_sync_fetch.py`** — 4 tests:
- `test_sync_single_project_fetches_cards_not_checklists`
- `test_compute_diff_receives_populated_cards_list`
- `test_sync_does_not_propose_recreating_existing_cards_on_second_run`
- `test_pull_updates_todo_title_from_trello_card_rename`

**`test_trello_group_labels.py`** — 5 tests:
- `test_group_label_created_on_first_sync`
- `test_group_label_reused_on_second_sync`
- `test_group_label_color_stable_across_runs`
- `test_card_gets_group_label_attached`
- `test_removing_group_label_in_trello_strips_local_group_tag_on_pull`

**`test_jira_apply_mapping_flat.py`** — 4 tests:
- `test_subtask_imports_as_flat_todo_with_group_tag`
- `test_no_parent_or_children_kwargs_on_todo_constructor`
- `test_todos_list_contains_parent_and_subtask_as_siblings`
- `test_empty_subtasks_list_noop`

**`test_jira_import_rules.py`** — ~10 tests covering the rule tree:
- `test_epic_mine_with_tasks_mine_all_imported_as_todos`
- `test_epic_mine_task_assigned_to_other_skipped`
- `test_task_with_epic_mine_skipped_at_task_pass_to_avoid_dup`
- `test_task_with_epic_other_becomes_standalone_project`
- `test_task_no_epic_becomes_project_with_subtask_todos`
- `test_task_no_epic_no_subtasks_becomes_empty_project`
- `test_subtask_parent_mine_handled_via_task_rule`
- `test_subtask_parent_other_epic_mine_handled_via_epic_rule`
- `test_orphan_subtask_becomes_own_project`
- `test_issue_removed_from_assignment_marks_project_detached`

### 6.2 Integration test

Seed a respx-mocked Jira with a mixed tree (1 epic + 3 tasks + 2 sub-tasks with mixed assignees); run `import_jira_issues`; assert the complete local state:
- epic:E1 project contains task_todos for my assigned tasks; group-tagged todos for sub-tasks where both parent task + sub-task are mine
- task:T2 project exists for my-task-in-other-epic
- task:ST5 empty project exists for orphan sub-task assigned to me

## 7. Deployment

- No data migration required — these are sync paths, not storage paths.
- Next `proj_sync` / `proj_jira_apply` after merge will re-run with the new rule tree; existing local projects get updated in place.
- Trello group labels appear on next `proj_trello_apply`; labels are additive (doesn't delete existing non-group labels).

## 8. Risks

- **Jira issue.type strings:** Jira uses issue type names ("Epic", "Task", "Sub-task") that are configurable per project. Survey confirms existing jira_sync has a check for these; use whatever constants the existing code uses rather than hardcoding new strings.
- **Performance:** `import_jira_issues` does N `jira_get_epic_issues` calls per epic. For users with dozens of epics this could be slow. Deferred optimization — measure first before tuning.
- **Trello label quota:** Trello boards have a label limit (infinite per Trello's docs, but UI caps at ~100 visible). For projects with 100+ group parents, the board's label list gets crowded. Not a blocker; flag in follow-up if it surfaces.
- **Dedup correctness:** if the test `test_task_with_epic_mine_skipped_at_task_pass_to_avoid_dup` fails, we'd create duplicate projects. Critical to get right. Integration test covers.

## 9. Out of scope

- Jira push (local → Jira). Not in scope per decision 3.
- Full-sync performance tuning.
- Trello list-based grouping (decision 2 chose labels, not dedicated lists).
- Completion cascade (decision 5 says no cascade).
- Reassignment-away cleanup UI (detachment happens silently; user discovers detached projects via project list).

## 10. Follow-up todos

- None anticipated at design time.
