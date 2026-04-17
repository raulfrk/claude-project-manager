# 647 SQL-only Storage — Implementation Plan

> Use `superpowers:subagent-driven-development` or execute inline. One serial agent per task per memory feedback (no parallel committing agents).

**Goal:** Consolidate todo/archive/decisions storage to SQL-only. YAML files deleted; JSON exports added for git-diff readability. Wizard handles v2→v3 migration + chains v1→v2→v3 for legacy projects.

**Spec:** `docs/superpowers/specs/2026-04-17-647-sql-only-storage-design.md`

**Predicates:** 636 Phase 1 + Phase 2 landed on dev.

**Test command patterns:**
- `cd plugins/proj/server && uv run pytest -q --no-cov`
- `cd /home/raul/worktrees/cpm/feat-647-sql-only-storage && uv run pytest installer/tests/migrations/ -q --no-cov`

---

## Task 1 — `sql_decisions.py` + `Decision` dataclass + `db.ensure_db` hook

**Files:**
- Modify: `plugins/proj/server/server/lib/models.py` — add `Decision` dataclass
- Create: `plugins/proj/server/server/lib/sql_decisions.py` — schema, ensure_table, load/save/append
- Modify: `plugins/proj/server/server/lib/db.py` — call `sql_decisions.ensure_table(conn)` in ensure_db
- Create: `plugins/proj/server/tests/test_sql_decisions.py` — 6 tests

**Test names:**
- `test_ensure_table_is_idempotent`
- `test_load_decisions_empty_returns_empty_list`
- `test_append_decision_assigns_id`
- `test_load_decisions_returns_insertion_order`
- `test_save_decisions_replaces_all`
- `test_decision_dataclass_roundtrip`

**Commit:** `feat(proj/lib): add sql_decisions table + Decision dataclass (647)`

---

## Task 2 — `schema_version.require_current` + TARGET bump

**Files:**
- Modify: `plugins/proj/server/server/lib/schema_version.py` — change `TARGET = 3`; add `require_current(cfg, project_name)` that raises `LegacyProjectError` pointing at `cpm-install --migrate-sql-only`. Existing `require_flat` stays (it's used by 636 Phase 2 storage guards) — we will update storage call sites in Task 3 to use `require_current` instead.
- Rename (via delete+create): `plugins/proj/server/tests/test_schema_version_require_flat.py` → `test_schema_version_require_current.py` with 2 tests mirroring require_flat's structure
- **IMPORTANT:** the existing `LegacyProjectError` message must be updated so the "run `cpm-install --migrate-flat`" text becomes "run `cpm-install --migrate-sql-only`" OR (better) "run `cpm-install --migrate`" (the new canonical entrypoint). Pick `--migrate` — orchestrator handles the full chain.

**Commit:** `feat(proj/lib): schema_version TARGET=3 + require_current (647)`

---

## Task 3 — `storage.py` SQL-only rewrite + `load_decisions`/`save_decisions`/`append_decision`

**Files:**
- Modify: `plugins/proj/server/server/lib/storage.py` — rewrite load_todos, save_todos, load_archive, save_archive to be SQL-only. Delete all YAML reads. Add load_decisions, save_decisions, append_decision that call sql_decisions. Every public function's first line is `schema_version.require_current(cfg, project_name)`.
- Update all tests that depend on YAML reads — they must seed via SQL now.
- Create: `plugins/proj/server/tests/test_storage_sql_only.py` — 5 tests:
  - `test_load_todos_reads_from_sql`
  - `test_save_todos_writes_sql_only_no_yaml_file`
  - `test_load_decisions_reads_from_sql`
  - `test_append_decision_adds_row`
  - `test_storage_raises_legacy_project_error_on_v2`

**Commit:** `feat(proj/lib): storage.py is SQL-only (todos/archive/decisions) (647)`

**Note:** this task will likely break many existing proj tests that write YAML directly to simulate state. Update them to use `sql_todos.save_todos` / `sql_archive.save_archive` / `sql_decisions.save_decisions` instead. That's the single biggest churn in this PR. Budget 30–60 min for test fixups.

---

## Task 4 — Tracking git flush: JSON exports

**Files:**
- Modify: `plugins/proj/server/server/lib/tracking_git.py` — add `write_json_exports(cfg, project_name)`; call it from start of `tracking_git_flush` (gated on `cfg.git_tracking.enabled`); change `git add` to explicit paths only (`data.db`, `todos.json`, `archive.json`, `decisions.json`, `proj.yaml`). Ensure `.gitignore` in tracking dir excludes `data.db-wal`, `data.db-shm`, `*.tmp`.
- Create: `plugins/proj/server/tests/test_tracking_git_flush_json.py` — 6 tests:
  - `test_write_json_exports_produces_sorted_stable_output`
  - `test_write_json_exports_creates_three_files`
  - `test_write_json_exports_noop_when_git_tracking_disabled`
  - `test_tracking_git_flush_stages_only_allowed_paths`
  - `test_tracking_git_flush_does_not_stage_legacy_yaml_files`
  - `test_tracking_git_flush_gitignores_wal_files`

**Commit:** `feat(proj/lib): tracking_git writes JSON exports for readable diffs (647)`

---

## Task 5 — `BackupSnapshot` adds `decisions.yaml` to OPTIONAL_FILES

**Files:**
- Modify: `installer/migrations/backup.py` — `OPTIONAL_FILES = ("archive.yaml", "data.db", "decisions.yaml")`
- Modify: `installer/tests/migrations/test_backup.py` — add test that decisions.yaml is captured when present + ignored when absent

**Commit:** `feat(installer/migrations): backup snapshot includes decisions.yaml (647)`

---

## Task 6 — `SqlOnlyMigration` + transform

**Files:**
- Create: `installer/migrations/sql_only.py` — `SqlOnlyMigration(MigrationRunner)` with same state machine as FlatTodoMigration
- Create: `installer/migrations/sql_only_transform.py` — `migrate_yaml_to_sql(project_dir: Path)` reads 3 YAML files, writes SQL rows, deletes YAML files after all SQL writes succeed
- Create: `installer/tests/migrations/test_sql_only_runner.py` — 3 tests (happy, rollback on transform failure, bump-only recovery when already migrated)
- Create: `installer/tests/migrations/test_sql_only_transform.py` — 4 tests covering todos+archive+decisions migration, cleanup of YAML files, intact-YAML on failure, empty-YAML handling

**Commit:** `feat(installer/migrations): SqlOnlyMigration runner + transform (647)`

---

## Task 7 — Orchestrator + CLI flags

**Files:**
- Create: `installer/migrations/orchestrator.py` — `run_migrations_for_project(project, run_ts, backup_root, integrations, strict_resync)` chains v1→v2→v3
- Modify: `installer/migrations/entry.py` — `run_pending_migrations` uses orchestrator; new `run_sql_only_dry_run` for the --migrate-sql-only flow
- Modify: `installer/main.py` — add `--migrate` (canonical), keep `--migrate-flat` as alias, add `--migrate-sql-only`, add `--migrate-dry-run` (covers both).
- Create: `installer/tests/migrations/test_migration_orchestrator.py` — 4 tests:
  - `test_orchestrator_v1_chains_through_both_migrations`
  - `test_orchestrator_v2_runs_sql_only_only`
  - `test_orchestrator_v3_is_noop`
  - `test_orchestrator_stops_at_v2_when_sql_only_fails`

**Commit:** `feat(installer): migration orchestrator + --migrate* CLI flags (647)`

---

## Task 8 — E2E tests + wizard UI snapshot updates

**Files:**
- Create: `installer/tests/migrations/e2e/test_e2e_v2_to_v3.py` — 1 test: already-flat project migrates to SQL-only successfully, YAML files gone, data.db contains all rows
- Create: `installer/tests/migrations/e2e/test_e2e_v1_to_v3_chain.py` — 1 test: legacy v1 project ends at v3 through chained migration
- Regenerate any Textual snapshot goldens that change due to UI label updates (migration review screen showing chain steps). If none change, skip this step.

**Commit:** `test(installer/migrations): e2e v2→v3 + v1→v3 chain (647)`

---

## Task 9 — Final sweep + merge

- [ ] `cd plugins/proj/server && uv run pytest -q --no-cov` — all pass (minus pre-existing test_claudemd_refresh_managed failures)
- [ ] `cd /home/raul/worktrees/cpm/feat-647-sql-only-storage && uv run pytest installer/tests/ -q --no-cov` — all pass
- [ ] Lint: `uv run ruff check server/ tests/` + format + basedpyright on proj plugin
- [ ] Rebase onto dev
- [ ] (pre-merge) Run `cpm-install --migrate` on the dev cpm tracking dir to bring it to v3 before merging, OR accept LegacyProjectError on next tool use
- [ ] FF-merge to local dev
- [ ] Push dev + watch CI

---

## Implementer notes

- **No parallel committing agents** (per memory feedback). One task at a time.
- **Task 3 is the biggest risk** — updates every test that writes YAML. Allocate effort; some tests may need wholesale rewrite.
- **Task 3 breaking change**: the moment `load_todos` requires v3, any test that runs against a v2 fixture fails. Either (a) update fixtures to write `schema_version: 3` + use `sql_todos.save_todos` for seeding, or (b) add a test helper `make_v3_project(tmp_path)` that does both. Pick (b) for DRY.
- **Task 7 `--migrate-flat` alias**: keep it working for one release cycle so 636 docs/CLI invocations don't break; emit a deprecation notice in its `--help` text.
- **Wizard Textual snapshots**: if the migration review screen now shows "v1 → v2 → v3" lineage strings, the 4 goldens from 636 Phase 1 (`test_screens.py`) need regen. Generate via `--snapshot-update`, verify, commit.
