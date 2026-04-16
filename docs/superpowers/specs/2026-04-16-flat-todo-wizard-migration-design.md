# Flat-Todo Wizard Migration — Design Spec

**Todo:** 636 (Phase 1 scope only — wizard migration mechanism + remote resync on run)
**Status:** Draft
**Date:** 2026-04-16
**Predicate:** Todo 624 (Python + hook changes for flat todo model) must ship first.
**Scope split:** Phase 2 (ongoing Jira/Trello/Todoist hook + sync code cleanup) gets a separate spec after Phase 1 lands.

## 1. Context

The project is migrating the todo data model from nested (`parent`/`children` fields) to flat (top-level todos with a `group:<parent-id>` tag). Todo 624 covers the server-side code changes that make the flat model first-class (flat-only enforcement on `todo_add`, removal of parent-field resolution in `_build_hook_fields`, hook config changes). This spec covers the **one-time migration** of existing projects + their Todoist/Trello/Jira remote state so that after 624 ships, users can upgrade seamlessly from nested-model data.

**Key constraints (from todo 636 notes):**
- Seamless + painless — no manual data-fixup steps required
- No data loss
- All existing integration link IDs (Todoist task IDs, Trello card IDs, Jira issue keys) preserved

## 2. Decisions (locked in during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Scope split | Phase 1 (wizard + resync) now, Phase 2 (hook/sync cleanup) separate spec later |
| 2 | Migration trigger UX | Interactive per-project prompt with preview |
| 3 | Integration link handling | Preserve IDs + best-effort remote resync (all three: Todoist, Trello, Jira) |
| 4 | `parent`/`children` schema fate | Hard-deleted post-migration |
| 5 | Detection signal | `schema_version: int` field in each project's `proj.yaml` |
| 6 | Rollback/backup | Per-project transactional with full backup |
| 7 | Resync scope | All three integrations in Phase 1 |
| 8 | Order vs. 624 | Predicate: 624 ships first, then Phase 1 |

Follow-up todos filed during brainstorming:
- **647** — Consolidate todo storage: YAML+SQL hybrid → SQL-only (YAML for configs only). Blocked by 636.

## 3. Architecture

New subpackage: `installer/migrations/`.

```
installer/migrations/
  __init__.py
  base.py           # MigrationRunner base class, backup/restore helpers, state machine
  flat_todo.py      # FlatTodoMigration (this migration)
  integrations/
    __init__.py
    base.py         # IntegrationResync protocol, Action + ResyncResult types
    todoist.py      # clear parentId on migrated children
    trello.py       # promote checklist items → standalone cards
    jira.py         # demote sub-tasks → standard issues (preserve epic link)
```

**Wizard hook:** `installer/app.py::run()` calls `run_pending_migrations(config, projects)` after plugin install/upgrade completes and before the wizard's exit/summary screen. Conditional: skipped entirely if `discover_pending()` returns an empty list.

**Integration modules** import each plugin's existing API client from `plugins/<plugin>/server/server/lib/`. The Todoist/Trello/Jira Python HTTP clients + auth logic already live there; the migration reuses them directly. No new MCP tools, no plugin-server changes specific to this migration.

**Data flow per project:**

```
discover          (schema_version < 2)
  → plan          (pure: build MigrationPlan incl. integration Actions)
  → prompt        (Rich UI: overview → per-project review → confirm)
  → [confirm]
  → backup        (snapshot todos.yaml, archive.yaml, data.db, proj.yaml + manifest)
  → flatten       (YAML rewrite + SQL ALTER TABLE rebuild)
  → resync        (Todoist/Trello/Jira modules execute Action list)
  → commit        (schema_version=2 → proj.yaml, atomic)
  → cleanup       (backup retention per --backup-retain)

[any failure between backup and commit] → restore from backup → continue next project
[resync failure] → log, mark partial, continue (no local revert)
```

## 4. Schema version + detection

**Field:** `schema_version: int` in each project's per-project `proj.yaml` (NOT the global `~/.claude/proj.yaml`).

| Value | Meaning |
|-------|---------|
| absent or `1` | Nested model, migration needed |
| `2` | Flat model (current target) |
| `>2` | Forward-compatibility — skip, don't downgrade |

**Detection** (`installer/migrations/base.py::discover_pending`):
1. Iterate tracked projects from global config
2. Read each project's `proj.yaml` via existing `config_load`
3. Return list of `(project_name, path, current_version)` entries where `current_version < 2`

**Edge cases:**
- Missing field → treat as version 1
- Unreadable/corrupted `proj.yaml` → log + skip (don't crash wizard)
- `>2` → skip silently

**Commit write path:** atomic merge via `config_update` pattern already in proj plugin — load → merge `schema_version: 2` → write temp file → rename.

**Rationale for per-project field:** each tracked project migrates independently; users may defer some projects if resync fails. Per-project field lets that happen.

**Note on promoting to SQL:** todo 647 will eventually move `schema_version` into an SQL `schema_info` table as part of the YAML→SQL consolidation. For Phase 1, `proj.yaml` stays authoritative (proj.yaml is config, not data — consistent with the "YAML for configs only" rule).

## 5. Migration runner state machine

**Class:** `FlatTodoMigration(MigrationRunner)` — one instance per project.

```
  [init] ──► DISCOVERED ──► PLANNED ──► CONFIRMED ──► BACKED_UP
                                    ↓                     │
                                  SKIPPED                 ▼
                                                    FLATTENED
                                                          │
                                                          ▼
                                                    RESYNCED
                                                          │
                                                          ▼
                                                    COMMITTED
                                                          │
                                                          ▼
                                                      CLEANED

  [any transition fail past BACKED_UP] ──► RESTORING ──► FAILED
```

**States:**
- `DISCOVERED` — schema_version < 2
- `PLANNED` — `MigrationPlan { parents, children, integration_actions: dict[Integration, list[Action]] }` built (pure; no network)
- `CONFIRMED` / `SKIPPED` — user prompt result
- `BACKED_UP` — full backup tarball written + verified (see §8)
- `FLATTENED` — YAML rewrite + SQL `ALTER TABLE` rebuild complete
- `RESYNCED` — all enabled integration modules executed
- `COMMITTED` — `schema_version: 2` written atomically to proj.yaml
- `CLEANED` — backup retained per `--backup-retain` flag
- `RESTORING` / `FAILED` — rollback done, error logged

**Invariants:**
- `COMMITTED` is the last-writer point. Commit failure reverts `schema_version` too (backup covers proj.yaml).
- Never leave a project in `FLATTENED` without `COMMITTED` — full rollback reverts both or neither.
- Resync failures do **not** trigger local rollback. Remote state is eventually consistent via next full sync; local data is authoritative. `--strict-resync` flag can override to abort on any resync error.

**Recovery path for SIGKILL / power loss between `FLATTENED` and `COMMITTED`:**
Plan phase checks `detect_already_flat(project) == True and schema_version < 2`. If so, skip flatten, go directly to commit (`RecoveryPath(bump_only)`). This also makes the whole runner idempotent — a second wizard invocation after a crash finishes the job without re-transforming data.

**Failure isolation:** per-project. One failure doesn't block other projects.

## 6. Wizard UX

Built with Textual (matches the existing installer TUI stack — `installer/screens/` is Textual `Screen` subclasses; snapshot tests use `pytest-textual-snapshot`). Three screens added under `installer/screens/migration_*.py`.

### Screen 1 — Overview

```
┌─ Flat-Todo Model Migration ─────────────────────────────────┐
│ 3 projects need migration to schema_version=2.              │
│                                                             │
│   Project                       Parents  Children  Remote   │
│   ─────────────────────────────────────────────────────    │
│   claude-project-manager        12       38        T,R,J    │
│   my-side-project               4        9         T        │
│   legacy-archive-me             0        0         –        │
│                                                             │
│ [Enter] review each project  [s] skip all  [q] quit         │
└─────────────────────────────────────────────────────────────┘
```

**Remote column badges:** `T` Todoist, `R` Trello, `J` Jira — only shown when that integration has live links on nested todos in that project.

### Screen 2 — Per-project review

```
┌─ claude-project-manager ────────────────────────────────────┐
│ Plan preview:                                               │
│   • 12 parent todos → each becomes flat w/ group:<id>       │
│   • 38 children → promoted to top-level with group:<parent> │
│   • No parent/children fields after migration               │
│                                                             │
│ Remote resync:                                              │
│   [T] Todoist: clear parentId on 38 child tasks             │
│   [R] Trello: promote 11 checklist items → standalone cards │
│   [J] Jira: demote 6 sub-tasks → standard issues            │
│                                                             │
│ Backup: ~/.claude/migrations/<run-ts>/cpm/                   │
│                                                             │
│ [m] migrate  [s] skip  [d] dry-run preview  [q] quit        │
└─────────────────────────────────────────────────────────────┘
```

**`[d]` dry-run preview** — two-tab view (Tab 1 local YAML diff sample; Tab 2 full remote action list). See §7.

**`[m]` migrate** — requires a second confirmation:
```
Proceed with 55 remote actions across Todoist, Trello, Jira? [y/N]
```

### Screen 3 — Progress + summary

Live progress per project during execution (spinner + current step label: `Backing up…` / `Flattening local…` / `Todoist resync…` / `Committing…`).

Final summary table with ✓/✗/⏭ per project + backup path + error log path.

### Non-TTY mode

When stdin isn't a TTY (CI / scripted install): wizard prints the overview and exits with a warning instructing the user to run `installer --migrate-flat` interactively. No silent auto-migration.

### CLI flags (introduced by this spec)

| Flag | Purpose |
|------|---------|
| `--migrate-flat` | Run the interactive migration flow standalone, outside a full wizard session. Same state machine as the post-install hook. |
| `--migrate-flat-dry-run` | Run `discover_pending()` + `plan()` only; write the report to `~/.claude/migrations/<ts>/dry-run.md`; no filesystem mutation outside the report file. |
| `--backup-retain=<N>` | Prune backup runs older than N days on next invocation. Default: keep forever. |
| `--strict-resync` | Treat remote resync failures as fatal: revert local flatten on any resync error. Default: off (log + continue, local flatten stands). |

Out of scope for Phase 1 but reserved: `--migrate-flat-retry <run-ts>` (replays retryable entries from `errors.log`).

### Exit codes

- `0` — all success or all skipped
- `2` — at least one project failed (local) or had resync failures
- `3` — user quit mid-flow

## 7. Preview + dry-run flow

`plan()` is pure — no network calls — and is invoked during both the `[d]` preview key and the standalone dry-run CLI mode.

### `[d]` preview (interactive)

**Tab 1 — Local diff:** sample of 3 todos rendered before/after in YAML, with `group:<id>` tag additions highlighted.

**Tab 2 — Remote actions:** full list grouped by integration, scrollable.

```
Todoist (38 actions)
  • task 6gPf6Qp4PXfwMQw5  set parentId=null  (todo 475.17)
  • task 6gPMWRr63VMrvcxX  set parentId=null  (todo 475.18)
  • ... 36 more

Trello (11 actions)
  • Create card "Fix logging levels" on list proj-tasks (from parent 475 checklist)
    Labels to copy: auth, security
    Will archive checklist "Children of 475" after completion
  • ... 10 more

Jira (6 actions)
  • CPM-123 (Sub-task under Epic CPM-100)
    Action: type → Story, parent → null, epic-link → CPM-100 (preserved)
  • ... 5 more
```

### Standalone dry-run mode

New CLI flag:

```
$ installer --migrate-flat-dry-run
```

Runs `discover_pending()` + `plan()` across all projects. Writes a markdown report to `~/.claude/migrations/<ts>/dry-run.md` with per-project sections and full action lists. No filesystem mutations outside the report file. Exit code 0.

## 8. Per-integration resync

### 8.1 Common interface

```python
class IntegrationResync(Protocol):
    def enabled_for(self, project: Project) -> bool: ...
    def plan(self, project: Project, migrated: list[Todo]) -> list[Action]: ...
    def execute(self, actions: list[Action]) -> ResyncResult: ...
```

- `plan()` is pure (zero network)
- `execute()` logs per-action outcomes to `~/.claude/migrations/<run-ts>/<project>/resync-errors.log` (JSONL)

### 8.2 Todoist (`integrations/todoist.py`)

**`enabled_for`:** `sync.todoist.enabled` AND at least one migrated todo has `todoist_task_id`.

**`plan`:** for each migrated child with a non-null `todoist_task_id`, emit `ClearParentAction(task_id)`.

**`execute`:** single `todoist_update_tasks` batch call with `parentId: null` per task. Chunked to 50/batch (Todoist API limit). Per-batch failure logs IDs and continues to next batch.

**Post-condition:** every migrated task shows as top-level in Todoist. Parent tasks untouched; each is now a flat cpm todo with the same 1:1 Todoist link.

### 8.3 Trello (`integrations/trello.py`)

**`enabled_for`:** `sync.trello.enabled` AND at least one migrated parent had `trello_checklist_id`.

**`plan`:** for each parent that had a checklist, walk the items. Each item becomes `PromoteChecklistItemAction(parent_card_id, checklist_id, item_id, target_todo_id, board_id, tasks_list_id)` carrying title + description + due date + label set.

**`execute` (per action):**
1. Create a new card on the board's tasks list via `batch_create_cards`
2. Copy label set from parent card to new card
3. Write new `trello_card_id` into the child todo's SQL/YAML record (reuses `todo_update` in-process)
4. Delete the checklist item via `delete_checklist_item`
5. After all items processed for a parent: if the checklist is empty, archive it via `delete_checklist`

The parent's own Trello card remains untouched.

**Edge case:** checklist item missing `trello_checklist_item_id` locally (drifted state). Plan phase flags it; execute phase skips it with a warning in the error log. Child stays flat locally without a Trello card until next full sync reconciles.

### 8.4 Jira (`integrations/jira.py`)

**`enabled_for`:** `sync.jira.enabled` AND at least one migrated todo has `jira_issue_key` on a synced sub-task.

**`plan`:** for each child with a Jira sub-task:
- Parent is Epic → `PromoteSubTaskAction(issue_key, strategy="unlink-parent", epic_link=<parent_key>)`
- Parent is Story/Task → `PromoteSubTaskAction(issue_key, strategy="unlink-parent", epic_link=<epic_of_parent_if_any>)`

**`execute` (per action):**
1. Transition issue type (sub-task → Story/Task) via `jira_update_issues`
2. Clear `parent` field
3. Set epic-link custom field to preserved value (if any)

**Edge case:** Jira project disallows type conversion. Logged as a per-project failure with an error message pointing the user at manual cleanup. Fallback strategies (e.g., create new issue + `supersedes` link + close old) are **out of scope for Phase 1**.

### 8.5 Failure semantics

- Per-action failures → `resync-errors.log` (structured JSONL)
- Integration-wide failure (auth token expired, API down) → `ResyncResult.aborted=True` → skip remaining actions for that integration, continue to next integration
- Any resync failure → warning in final summary + exit code 2 — **but local flatten is not reverted**

## 9. Backup + rollback

### Backup artifact

```
~/.claude/migrations/<run-ts>/<project-slug>/
  todos.yaml         # exact copy of pre-migration
  archive.yaml
  data.db            # full SQLite file (after PRAGMA wal_checkpoint)
  proj.yaml          # pre-migration metadata (schema_version absent or =1)
  manifest.json      # {project, run_ts, cpm_version, source_paths, checksums}
```

**Checksums:** sha256 of each file in manifest. Restore path verifies before overwriting.

**Atomicity:** write to `<dir>.tmp`, verify all files + manifest, rename to final path.

**Retention:** kept forever by default. `--backup-retain=<N>` flag prunes runs older than N days on next wizard invocation.

### Restore trigger table

| Failure during step | Restore action |
|---------------------|----------------|
| BACKED_UP (write fails) | No restore — nothing mutated yet. Mark FAILED. |
| FLATTENED (YAML/SQL rewrite fails) | Full restore from backup. Verify checksums. Mark FAILED. |
| RESYNCED (integration error) | **No restore.** Local flatten stands. Log error; integration result marked `partial`. |
| COMMITTED (schema_version write fails) | Full restore (backup covers proj.yaml). Mark FAILED. |
| CLEANED (retention) | No impact on migration success. Log only. |

### Concurrent run guard

Lock file `~/.claude/migrations/.lock` (flock-based) held for the whole run. Collision: second wizard prints `Migration already running (pid X)` and exits. Released via atexit + signal handler on any exit path.

### Error log format

`~/.claude/migrations/<run-ts>/errors.log` — JSONL:

```json
{"ts":"...","project":"cpm","phase":"resync:trello","action_id":"promote-checklist-item-42","error_class":"TrelloAPIError","message":"...","retryable":true}
```

Structured so a future `installer --migrate-flat-retry <run-ts>` command could read the log and redo only retryable failures. (Retry command is **not** part of Phase 1 scope — the log format is prepared for it.)

## 10. Testing

### 10.1 Unit tests — `tests/installer/migrations/`

1. `test_discover.py` — missing field, v1, v2, v3 (skip), corrupted proj.yaml, missing proj.yaml
2. `test_plan.py` — `MigrationPlan` across fixture projects (single parent, no children, parent-with-no-parent, etc.)
3. `test_backup.py` — snapshot write + manifest, atomic rename, restore byte-identity, checksum rejection on tampered backup
4. `test_flatten_local.py` — YAML transform (parent/children → `group:<id>` tag), SQL ALTER TABLE rebuild (new table → copy → swap → drop), idempotency, `next_child_id` removal
5. `test_state_machine.py` — valid transitions, invalid transitions raise, `RecoveryPath(bump_only)` fires when `detect_already_flat=True and schema_version<2`
6. `test_lock.py` — flock acquire/release, collision early-exit, SIGINT releases
7. `test_integrations_plan.py` — per-integration `plan()` purity: fixture in → expected `Action` list out; `enabled_for()` honors config + live-link presence

### 10.2 Integration tests — `tests/installer/migrations/integration/`

Live APIs mocked via `respx` (installed per todo 635). One fixture per integration:

1. `test_todoist_resync.py` — 38 tasks → 1 batched update; partial failure (429) logs IDs + continues; auth failure → aborted
2. `test_trello_resync.py` — full checklist promotion; missing `trello_checklist_item_id` skipped with warning
3. `test_jira_resync.py` — sub-task under Epic (keep link); sub-task under Story (inherit grandparent epic); project rejects type conversion (logged failure)

### 10.3 End-to-end tests — `tests/installer/migrations/e2e/`

Full wizard flow in a tmpdir sandbox, SaaS responses mocked, `~/.claude/` stubbed:

1. `test_e2e_happy_path.py` — 3 projects mixed integrations, user confirms all, all reach `COMMITTED`
2. `test_e2e_rollback.py` — SQL ALTER failure on project 2; projects 1 + 3 commit, project 2 rolls back to v1, exit 2
3. `test_e2e_resync_partial.py` — Trello 500 on one action; local committed, remote partial, warning in summary + error log
4. `test_e2e_power_loss_recovery.py` — SIGKILL between `FLATTENED` and `COMMITTED` on project 2; second run takes `RecoveryPath(bump_only)` to v2
5. `test_e2e_dry_run.py` — `--migrate-flat-dry-run` writes report, no mutations, exit 0
6. `test_e2e_non_tty.py` — stdin redirected; warning + exit 0 without migrating

### 10.4 Snapshot tests — Textual TUI

One golden per screen: overview, per-project review, dry-run Tab 1, dry-run Tab 2, progress, summary. Reuses `pytest-textual-snapshot` (already a dev dep). **First CI run after new goldens is expected to flake — rerun workflow before investigating** (per CLAUDE.md).

### 10.5 Coverage target

≥ 85% line coverage on `installer/migrations/`. Higher than cpm convention (perms 82.6%, worktree 80.8%, proj 79.5%) because migration is destructive + one-shot per user and has fewer observers.

## 11. Out of scope (Phase 2 or later)

- **Hook config cleanup.** `parentId: "${parent_todoist_task_id}"` and `parent_key: "${jira_issue_key}"` param mappings remain in the default-hooks.yaml files until Phase 2. They become no-ops post-migration because `parent_todoist_task_id` and the parent-chain resolution in `_build_hook_fields` are removed by todo 624. Phase 2 spec removes them.
- **`/proj:flatten-children` skill changes.** The existing skill continues to work on the unmigrated read path until 624 + Phase 1 ship. Phase 2 decides whether to retire the skill or keep it as a per-parent utility.
- **SQL-only consolidation.** Covered by todo 647 (blocked by 636).
- **Retry command (`installer --migrate-flat-retry`).** Log format is forward-compatible; actual retry logic not in Phase 1.
- **Automatic (non-interactive) migration mode.** Ruled out per decision #2.
- **Full remote teardown/rebuild.** Ruled out per decision #3.

## 12. Follow-up todos

- **624** (predicate) — Python + hook changes for flat todo model. Must ship first.
- **647** (blocked by 636) — SQL-only storage consolidation.
- **636 Phase 2** (to be filed after Phase 1 lands) — Hook config + sync code cleanup.
