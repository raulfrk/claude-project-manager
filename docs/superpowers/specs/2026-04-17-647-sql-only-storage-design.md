# 647 — SQL-only Storage Consolidation Design Spec

**Todo:** 647 (unblocked by 636 Phase 1 + Phase 2)
**Status:** Draft
**Date:** 2026-04-17
**Predicates:** 636 Phase 1 + Phase 2 landed on dev (schema_version=2, flat model, `LegacyProjectError` guard active).

## 1. Context

The proj plugin currently runs a YAML+SQL hybrid: `todos.yaml` / `archive.yaml` / `decisions.yaml` are the source of truth and a parallel SQLite mirror (`data.db`) is populated via hook side-effects on mutations. The split doubles the write surface, creates drift risk, and complicates migrations. 647 consolidates to SQL-only: `data.db` becomes the single source of truth; YAML files are deleted; a derived JSON export layer preserves human-readable git-diff history.

## 2. Decisions (locked during brainstorming 2026-04-17)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Git-tracking diff format | JSON exports (todos/archive/decisions.json) regenerated on every mutation. SQL is source-of-truth; JSON is derived-for-git. |
| 2 | `decisions.yaml` disposition | Moves to SQL (`decisions` table). JSON export preserves readable log. |
| 3 | `schema_version` location | Stays in `proj.yaml` (config, not data). Bumps from 2 → 3. |
| 4 | Migration path | Installer wizard runs a new `SqlOnlyMigration` phase for v2→v3. Legacy v1 projects chain v1→v2→v3 via orchestrator. |

## 3. Architecture

**New/modified files:**

```
plugins/proj/server/server/lib/
  storage.py              # REWRITE: SQL-only reads/writes; invokes JSON export on mutations
  sql_decisions.py        # NEW — schema, load_decisions, save_decisions, append_decision
  tracking_git.py         # MODIFY — generate JSON exports before commit; stage data.db + *.json + proj.yaml only
  schema_version.py       # MODIFY — TARGET=3; add require_current()
  models.py               # MODIFY — add Decision dataclass
  db.py                   # MODIFY — call sql_decisions.ensure_table from ensure_db

installer/migrations/
  sql_only.py             # NEW — SqlOnlyMigration(MigrationRunner) for v2→v3
  sql_only_transform.py   # NEW — migrate_yaml_to_sql() reads raw YAML, writes SQL
  orchestrator.py         # NEW — runs per-project migration chain (v1→v2→v3)
  entry.py                # MODIFY — add run_sql_only_migration + update run_pending_migrations to orchestrate chain
  backup.py               # MODIFY — add decisions.yaml to OPTIONAL_FILES

installer/main.py          # MODIFY — add --migrate-sql-only CLI flag; rename --migrate-flat to --migrate (alias kept)

plugins/proj/server/tests/
  test_sql_decisions.py                           # NEW
  test_storage_sql_only.py                        # NEW
  test_tracking_git_flush_json.py                 # NEW
  test_schema_version_require_current.py          # NEW (rename from require_flat test)

installer/tests/migrations/
  test_sql_only_runner.py                          # NEW
  test_sql_only_transform.py                       # NEW
  test_migration_orchestrator.py                   # NEW
  e2e/test_e2e_v2_to_v3.py                         # NEW
  e2e/test_e2e_v1_to_v3_chain.py                   # NEW
```

**Data model transition summary:**

| Version | Todo model | Storage | Status |
|---------|-----------|---------|--------|
| 1 | nested (`parent`/`children`) | YAML hybrid | pre-636 legacy |
| 2 | flat (`group:<id>` tag) | YAML hybrid | post-636, current dev |
| 3 | flat (`group:<id>` tag) | SQL-only | post-647 (this spec) |

## 4. Storage layer (`storage.py`) rewrite

Every public function wraps `schema_version.require_current(cfg, project_name)` as its first call. If schema_version < 3, raises `LegacyProjectError` with actionable `cpm-install --migrate-sql-only` message.

```python
def load_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    schema_version.require_current(cfg, project_name)
    return sql_todos.load_todos(cfg, project_name)


def save_todos(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    schema_version.require_current(cfg, project_name)
    sql_todos.save_todos(cfg, project_name, todos)
    # Tracking flush is invoked by the router hook chain; it calls
    # write_json_exports() internally as its first step.


def load_archive(cfg, project_name) -> list[Todo]: ...          # same pattern
def save_archive(cfg, project_name, archive) -> None: ...
def load_decisions(cfg, project_name) -> list[Decision]: ...    # NEW
def save_decisions(cfg, project_name, decisions) -> None: ...   # NEW
def append_decision(cfg, project_name, decision) -> None: ...   # NEW — inserts one row
```

All YAML file reads are deleted from storage.py. `proj.yaml` is still touched for schema_version / project meta reads, but via `schema_version.current()` + `sql_meta` — no yaml.safe_load in storage.py post-647.

## 5. `sql_decisions.py` + Decision dataclass

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    text TEXT NOT NULL,
    todo_id TEXT,
    tags TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_decisions_todo_id ON decisions(todo_id);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);
```

**Dataclass (in `models.py`):**

```python
@dataclass
class Decision:
    timestamp: str
    text: str
    todo_id: str | None = None
    tags: list[str] = field(default_factory=list)
    id: int | None = None  # assigned by SQL
```

**Module functions:**

- `ensure_table(conn)` — creates table + indexes if absent (called from `db.ensure_db`)
- `load_decisions(cfg, project_name) -> list[Decision]` — SELECT all, order by `id` ASC (insertion order)
- `save_decisions(cfg, project_name, decisions)` — DELETE + bulk INSERT in a transaction (rewrite pattern, used when bulk-editing)
- `append_decision(cfg, project_name, decision) -> Decision` — single INSERT, returns Decision with assigned id

## 6. Git-tracking rewrite (`tracking_git.py`)

New helper:

```python
def write_json_exports(cfg: ProjConfig, project_name: str) -> None:
    """Write derived JSON snapshots of todos/archive/decisions into the tracking dir.

    These files exist for git-diff readability only. SQL is the source of truth.
    No-op when git_tracking.enabled is False.
    """
    if not cfg.git_tracking.enabled:
        return
    proj_dir = Path(cfg.tracking_dir).expanduser() / project_name
    _write_json(proj_dir / "todos.json", sql_todos.load_todos(cfg, project_name))
    _write_json(proj_dir / "archive.json", sql_archive.load_archive(cfg, project_name))
    _write_json(proj_dir / "decisions.json", sql_decisions.load_decisions(cfg, project_name))


def _write_json(path: Path, items: list) -> None:
    payload = [dataclasses.asdict(t) for t in items]
    payload.sort(key=lambda d: d.get("id", ""))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)
```

Modified `tracking_git_flush`:

```python
def tracking_git_flush(cfg, project_name, commit_message):
    if not cfg.git_tracking.enabled:
        return
    write_json_exports(cfg, project_name)
    proj_dir = Path(cfg.tracking_dir).expanduser() / project_name
    _git(proj_dir, "add", "data.db", "todos.json", "archive.json", "decisions.json", "proj.yaml")
    if _has_staged_changes(proj_dir):
        _git(proj_dir, "commit", "-m", commit_message)
```

**Important:** the `git add` is by explicit path — never `-A`. Tmp files (`.json.tmp`) and any residual legacy `.yaml` must not leak into commits.

**gitignore** in each tracking dir: add `data.db-wal` + `data.db-shm` if not already present (created by `tracking_git.ensure_gitignore` once per project).

## 7. Migration wizard

### 7.1 `SqlOnlyMigration(MigrationRunner)`

Same state machine as `FlatTodoMigration`. Phases:
- `_plan` — enumerate YAML files present (todos.yaml, archive.yaml, decisions.yaml); build plan with counts.
- `_backup` — snapshot via `BackupSnapshot` (now includes `decisions.yaml` in `OPTIONAL_FILES`).
- `_flatten` — calls `sql_only_transform.migrate_yaml_to_sql(project_dir)`:
  - Read `todos.yaml` + upsert rows into `todos` table (using existing `sql_todos.save_todos`)
  - Read `archive.yaml` + upsert into `archive_todos` via `sql_archive.save_archive`
  - Read `decisions.yaml` + upsert into `decisions` via `sql_decisions.save_decisions`
  - Delete the three YAML files after all SQL writes succeed
- `_resync` — no-op (no SaaS coordination needed; flat model + integration IDs already synced in Phase 1)
- `_commit` — `schema_version.bump_schema_version(proj_yaml_path, 3)`
- `_restore` — BackupSnapshot.restore() (puts YAML files back, reverts proj.yaml schema_version)

### 7.2 `orchestrator.py::run_migrations_for_project`

Chains the two migrations. Pseudo-code:

```python
def run_migrations_for_project(project, run_ts, backup_root, ...) -> RunResult:
    current = project.current_version
    if current <= 1:
        flat = FlatTodoMigration(project, run_ts, backup_root, ...)
        flat.plan(); flat.confirm(); flat.execute_local(); flat.commit()
        if flat.state != MigrationState.COMMITTED:
            return RunResult(stopped_at=1, reason="flat-todo migration failed")
        project = project.refreshed()  # re-read schema_version from disk
    if project.current_version <= 2:
        sql = SqlOnlyMigration(project, run_ts, backup_root, ...)
        sql.plan(); sql.confirm(); sql.execute_local(); sql.commit()
        if sql.state != MigrationState.COMMITTED:
            return RunResult(stopped_at=2, reason="sql-only migration failed")
    return RunResult(stopped_at=TARGET, reason="complete")
```

Failure: v1→v2 succeeds but v2→v3 fails → project stays at v2 (safe, flat-model fully functional). Next wizard run picks up where we stopped.

### 7.3 Wizard UI changes

The existing `MigrationReviewScreen` displays a "plan" block with parents/children/remote-actions. Extend to show migration steps: "v1 → v2 → v3 (2 steps)" header when both migrations apply, "v2 → v3 (1 step)" when only sql-only applies. Snapshot goldens need regen.

### 7.4 CLI flags

- `cpm-install --migrate` — run full chain for any project needing upgrade (new canonical flag)
- `cpm-install --migrate-flat` — alias for `--migrate` (kept for backward-compat)
- `cpm-install --migrate-sql-only` — run only v2→v3 (errors if any project is v1)
- `cpm-install --migrate-dry-run` — run the chain plan only, write report

## 8. Backup/restore changes

`BackupSnapshot.OPTIONAL_FILES` becomes `("archive.yaml", "data.db", "decisions.yaml")`. Post-v3, `decisions.yaml` doesn't exist, so it's absent from the snapshot — which is the expected behavior.

Restore path unchanged — copies back whatever was captured.

## 9. Testing strategy

### 9.1 Unit tests

- `test_sql_decisions.py` — ensure_table idempotency, load/save/append roundtrip, Decision dataclass shape, todo_id FK soft-link behavior (not a real FK at SQL level; tested via inserts)
- `test_storage_sql_only.py` — load_todos reads from SQL (seeded directly via sql_todos.save_todos), save_todos writes SQL, LegacyProjectError raised for v1/v2 projects with clear actionable message
- `test_tracking_git_flush_json.py` — write_json_exports produces stable output across multiple invocations (no diff on no-op); tracking_git_flush stages only data.db + *.json + proj.yaml; legacy *.yaml files are never staged even if present on disk
- `test_schema_version_require_current.py` — raises for schema_version < 3, passes for 3, passes for future versions (forward-compat)

### 9.2 Migration tests

- `test_sql_only_runner.py` — SqlOnlyMigration state machine (3 tests: happy path, rollback on transform failure, bump-only recovery)
- `test_sql_only_transform.py` — migrate_yaml_to_sql migrates a fixture project (todos+archive+decisions YAML) into SQL, deletes YAML files, leaves intact on exception
- `test_migration_orchestrator.py` — v1 project chains v1→v2→v3; v2-only project runs v2→v3; v3-only project is noop; v1→v2 failure stops chain cleanly at v1

### 9.3 E2E tests

- `test_e2e_v2_to_v3.py` — already-flat project migrates to SQL-only; data.db has todos+archive+decisions rows; YAML files gone; tracking dir commits JSON exports
- `test_e2e_v1_to_v3_chain.py` — legacy v1 project ends at v3 via chained migration; all state consistent

### 9.4 Coverage target

≥79.5% proj plugin (unchanged convention).

## 10. Migration deployment considerations

Pre-merge: dev environment's cpm tracking dir must run `cpm-install --migrate` (or user accepts `LegacyProjectError` on next tool use).

CI: ephemeral test projects create at v3 directly (tests instantiate projects with `schema_version: 3` in fixtures); no migration dance needed in CI.

## 11. Out of scope

- Todo 625 (Trello+Jira full-sync audit for flat model) — deferred
- Todo 637 (Jira sync architecture revisit) — deferred
- Any YAML→JSON conversion for other files (worktree.yaml, hooks.yaml, proj.yaml) — config files stay YAML per established convention
- Performance tuning of SQL queries — assumed adequate; revisit only if regression measurements show otherwise

## 12. Risks

- **Git tracking commit volume:** JSON exports regenerate on every mutation. A 500-todo project writes a 500-entry JSON on each save. File size ~100–200KB; git handles that fine. Regeneration is CPU-bound but fast (single SELECT + json.dumps).
- **Migration of a very large legacy project:** orchestrator runs flat-todo migration in memory then SQL-only migration. Peak memory is bounded by todo count × fields ~= few MB for a big project. Not a concern.
- **Dev environment:** the cpm project itself is at v2 (or v1 if wizard never ran). Must migrate before this branch's code runs.
- **JSON export path:** writing to `tmp` + rename is atomic; no partial-file risk. But the write happens on every mutation; if many mutations occur concurrently (unlikely for CLI tools but possible in scripted scenarios), writes race. Existing hybrid storage has the same risk; not a regression.

## 13. Follow-up todos (post-647)

- 625 remains pending — Trello/Jira full-sync audit
- No new follow-ups anticipated.
