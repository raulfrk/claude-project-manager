# 625 — Sync Flat-Model Alignment Implementation Plan

> Serial implementation. One agent per task (no parallel git-committing agents).

**Spec:** `docs/superpowers/specs/2026-04-17-625-sync-flat-model-alignment-design.md`

**Goal:** Fix 2 correctness bugs in sync code + implement Trello group labels + Jira import rule tree for the flat model.

**Test command:** `cd plugins/proj/server && uv run pytest -q --no-cov`

---

## Task 1 — Bug B: Jira `apply_mapping` Todo constructor fix

**Files:**
- Modify: `plugins/proj/server/server/tools/jira_sync.py` — the nested-Todo construction block (was at lines 1108-1125 before Phase 2; may have shifted; grep for `parent=parent_todo.id` or `parent_todo.children.append`)
- Create: `plugins/proj/server/tests/test_jira_apply_mapping_flat.py` — 4 tests per spec §6.1

**Change:** sub-task Todo built with `tags=list(subtask_tags) + [f"group:{parent_todo.id}"]`, no `parent`/`children`/`parent_todo.children.append`.

**Commit:** `fix(jira): apply_mapping uses flat-model group tag instead of nested kwargs (625)`

---

## Task 2 — Bug A: Trello full-sync fetch alignment

**Files:**
- Modify: `plugins/proj/server/server/tools/trello_full_sync.py` — `_sync_single_project` fetches cards via `get_cards_by_list_id` for tasks + done lists, `get_lists(board_id)`, `get_card(project_card_id)`; builds `trello_data = {"cards": ..., "lists": ..., "project_card": ...}` for `compute_diff`. Delete the checklist-walk code.
- Create: `plugins/proj/server/tests/test_trello_full_sync_fetch.py` — 4 tests per spec §6.1

**Commit:** `fix(trello): full_sync fetches cards for compute_diff instead of checklists (625)`

---

## Task 3 — Trello group labels

**Files:**
- Modify: `plugins/proj/server/server/tools/trello_sync.py` — `compute_diff` emits label-ensure + label-attach actions for each `group:*` tag on each card being created/updated. Add `_ensure_group_label(board_id, name)` + `_stable_color_for(name)` helpers.
- Modify: same file — pull path detects `group:*` labels on Trello cards and syncs to local todo's tags (add/remove).
- Create: `plugins/proj/server/tests/test_trello_group_labels.py` — 5 tests per spec §6.1

**Commit:** `feat(trello): group:<id> labels on grouped child cards (625)`

---

## Task 4 — Jira import rule tree rewrite

**Files:**
- Modify: `plugins/proj/server/server/tools/jira_sync.py` — rewrite `apply_mapping` per spec §5.2 rule tree: Pass 1 identifies my epics; Pass 2 iterates my issues with type-based dispatch to `_import_epic` / `_import_task_as_project` / `_import_orphan_subtask`. Dedup via `my_epic_keys` set + `parent_mine or epic_mine` check.
- Add `ensure_project(cfg, name, source)` + `ensure_todo(cfg, project, source, extra_tags=[])` helper functions in the same module (or factor into a small `jira_import_helpers.py` if cleaner).
- Create: `plugins/proj/server/tests/test_jira_import_rules.py` — ~10 tests per spec §6.1 covering the full rule tree.

**Commit:** `feat(jira): import rule tree aligned with flat model (625)`

---

## Task 5 — Jira reassignment detachment

**Files:**
- Modify: `plugins/proj/server/server/tools/jira_sync.py` — after the import pass, enumerate existing local projects whose name is `epic:*` or `task:*`; any whose source issue is no longer in `my_issues` gets:
  - If it's a placeholder (zero todos AND zero content) → archive via `project_archive`
  - Else → set `jira_detached=true` on the project meta + stop syncing updates
- Add test coverage (2 tests) in `test_jira_import_rules.py` (append) — `test_orphan_placeholder_project_archived_when_unassigned` + `test_task_project_with_todos_marked_detached_when_unassigned`

**Commit:** `feat(jira): detach or archive projects when assignment is removed (625)`

---

## Task 6 — Final sweep + merge

- [ ] `cd plugins/proj/server && uv run pytest -q --no-cov` — all pass (minus pre-existing test_claudemd_refresh_managed failures)
- [ ] Lint: `uv run ruff check server/ tests/` + `ruff format --check` + `basedpyright server/`
- [ ] Rebase onto dev
- [ ] FF-merge to local dev + push + watch CI

---

## Implementer notes

- **Serial tasks** — no parallel committing agents. One task, one commit, next task.
- **Task 1 is the smallest/safest** — land it first to unbreak Jira pull immediately.
- **Task 2 is medium** — verify `get_cards_by_list_id` signature matches what the Trello client exposes; may need adjustment.
- **Task 4 is the biggest** — the rule tree is documented in the spec. Follow the spec's code snippet as the authoritative implementation template.
- **`jira_get_user_issues` signature:** check the existing usage in `jira_sync.py` to see how it's called (probably already filters by assignee). Reuse the same call pattern.
- **Jira issue type strings:** "Epic", "Task", "Sub-task" may differ per Jira project config. The existing code likely has constants — use them.
- **`ensure_project` / `ensure_todo` idempotency:** key lookup by project.name / todo's source.key is critical — re-running the importer must update in place, not duplicate.
