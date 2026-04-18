# 656 — Wizard Discovery Fix Implementation Plan

> Single-agent serial. One commit per task.

**Spec:** `docs/superpowers/specs/2026-04-18-656-wizard-discovery-fix-design.md`

**Goal:** Make `cpm-install --migrate-dry-run` actually find projects in the real environment.

**Test command:** `cd /home/raul/worktrees/cpm/feat-656-wizard-discovery-fix && uv run pytest installer/tests/migrations/ -q --no-cov` + `cd plugins/proj/server && uv run pytest tests/test_schema_version*.py -q --no-cov`

---

## Task 1 — `schema_version.py` rewrite (proj plugin)

**Files:**
- Modify: `plugins/proj/server/server/lib/schema_version.py` — `current()` reads `.schema-version` text file. New `bump_schema_version(project_dir, version)` writes it atomically.
- Update: `plugins/proj/server/tests/test_schema_version.py` + `test_schema_version_require_*.py` — fixtures write `.schema-version` instead of `proj.yaml`.
- Run: `cd plugins/proj/server && uv run pytest tests/test_schema_version*.py -q --no-cov` — all pass.

**Commit:** `fix(proj/lib): schema_version uses .schema-version text file (656)`

---

## Task 2 — `installer/migrations/detect.py` rewrite

**Files:**
- Modify: `installer/migrations/detect.py` — `read_schema_version(path)` reads `.schema-version`; `bump_schema_version(project_dir, version)` writes it. `discover_pending` looks at `<project_dir>/.schema-version`.
- Modify: `installer/migrations/types.py` — rename `PendingProject.proj_yaml_path` → `schema_version_path`.
- Update: `installer/migrations/conftest.py::tmp_project` fixture writes `.schema-version`.
- Update: `installer/tests/migrations/test_detect.py` — all fixtures write `.schema-version`.
- Run target tests + verify all green.

**Commit:** `fix(installer/migrations): detect.py uses .schema-version + PendingProject field rename (656)`

---

## Task 3 — Migration runners commit-phase update

**Files:**
- Modify: `installer/migrations/flat_todo.py::FlatTodoMigration._commit` — call `bump_schema_version(self.project.path, 2)` (path-based, not yaml-based).
- Modify: `installer/migrations/sql_only.py::SqlOnlyMigration._commit` — same with version=3.
- Update any calls to old `bump_schema_version(proj_yaml_path, version)` signature.
- Run: `cd /home/raul/worktrees/cpm/feat-656-wizard-discovery-fix && uv run pytest installer/tests/migrations/test_flat_todo_runner.py installer/tests/migrations/test_sql_only_runner.py -q --no-cov`.

**Commit:** `fix(installer/migrations): runners write .schema-version on commit (656)`

---

## Task 4 — `load_project_list()` rewrite

**Files:**
- Modify: `installer/cli.py::load_project_list()` — read `<tracking_dir>/active-projects.yaml` per spec §4.
- Create: `installer/tests/migrations/test_load_project_list.py` — 4 new tests per spec §8.1.

**Commit:** `fix(installer/cli): load_project_list reads active-projects.yaml (656)`

---

## Task 5 — E2E + CLI test fixture rewrites

**Files:**
- Modify: `installer/tests/migrations/e2e/conftest.py::home_with_projects` — build `<HOME>/projects/tracking/active-projects.yaml` registry + per-project `.schema-version` (omit for v1 to test absent-file → 1 path).
- Modify: `installer/tests/migrations/test_cli_flags.py::test_dry_run_flag_exits_zero_without_mutation` — set up a real-shape registry so dry-run iterates projects (currently asserts exit 0 with no projects; update to assert exit 0 with non-empty report).
- Run: full installer migrations test suite + e2e — all green.

**Commit:** `test(installer/migrations): fixtures use real-shape active-projects.yaml + .schema-version (656)`

---

## Task 6 — Manual smoke verification

- [ ] Run `cpm-install --migrate-dry-run` against the developer's actual `~/projects/tracking/`
- [ ] Verify the report at `~/.claude/migrations/<ts>/dry-run.md` is NON-EMPTY and lists pending projects
- [ ] Spot-check 2 projects' state (cpm + one other) — confirm parent counts / sub-task counts look right

If the smoke test fails, file follow-up + iterate.

---

## Task 7 — Final sweep + merge

- Full proj + installer test suites green
- Lint: `ruff check + format --check + basedpyright` on changed files
- Rebase onto dev
- FF-merge + push + watch CI

---

## Implementer notes

- **Serial only**: per memory feedback, no parallel git-committing agents.
- **PendingProject field rename**: grep `proj_yaml_path` across all installer/ + plugins/proj/server/ code; update each call site.
- **Test fixture rewrites are broad but mechanical**: sed-like replacements. Watch for tests that write multi-key proj.yaml (some may have just `schema_version`, others may have `name` + `schema_version`); split into `.schema-version` (single int) plus the rest going into either nothing (deleted) or actual meta.yaml fixtures (probably nothing — the tests don't usually need full meta).
- **Don't accidentally write `.schema-version.tmp`** in any test fixture — atomic-write helper handles that internally.
- **Keep `require_flat` and `require_current`**: they're used by storage entry guards and call `current()` — no signature change needed.
