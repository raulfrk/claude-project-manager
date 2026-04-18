# 656 — Wizard Migration Discovery Fix Design Spec

**Todo:** 656
**Status:** Draft
**Date:** 2026-04-18
**Severity:** Ship-blocker — wizard claims "no projects need migration" against real environments with 20+ projects needing migration.

## 1. Context

Discovered 2026-04-18 during a smoke-test of `cpm-install --migrate-dry-run` against the developer's actual `~/projects/tracking/` directory. The dry-run report contained only "No projects require migration." despite the developer having 20+ projects that pre-date 636 (still on YAML+SQL hybrid).

Root cause: 636 + 647 wizard work assumed a per-project `proj.yaml` file with a `schema_version` field, and assumed the global `~/.claude/proj.yaml` had a `projects:` map. Both assumptions are wrong:

- `~/.claude/proj.yaml` is **global config only** (no projects map).
- The real project registry is `<tracking_dir>/active-projects.yaml` (proj plugin's `storage.load_index`).
- Per-project metadata is `<project_dir>/meta.yaml`, not `<project_dir>/proj.yaml`.
- `meta.yaml` is a **derived export** of `sql_meta` — writing to it directly gets overwritten on next sql_meta sync.

E2E tests passed because all wizard fixtures created their own synthetic `proj.yaml` per project — never exercised against real proj-plugin file conventions.

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Per-project schema_version storage | Tiny `.schema-version` file (single-line int) at `<project_dir>/.schema-version`. Single-purpose, isolated, no SQL schema change. |
| 2 | Project registry source | `<tracking_dir>/active-projects.yaml`'s `projects:` map. |
| 3 | tracking_dir source | `~/.claude/proj.yaml.tracking_dir` (default `~/projects/tracking`). |
| 4 | Archived projects | Excluded from migration discovery. |
| 5 | Field rename | `PendingProject.proj_yaml_path` → `schema_version_path`. |

## 3. Architecture

**Files modified:**

```
installer/cli.py                                          # load_project_list() rewrite
installer/migrations/types.py                             # PendingProject.proj_yaml_path → schema_version_path
installer/migrations/detect.py                            # read_schema_version + bump_schema_version use .schema-version
installer/migrations/flat_todo.py                         # commit phase writes .schema-version
installer/migrations/sql_only.py                          # commit phase writes .schema-version
plugins/proj/server/server/lib/schema_version.py          # current() + new bump_schema_version use .schema-version

installer/tests/migrations/conftest.py                    # tmp_project fixture uses .schema-version
installer/tests/migrations/test_detect.py                 # fixtures use .schema-version
installer/tests/migrations/test_cli_flags.py              # uses real-shape active-projects.yaml
installer/tests/migrations/e2e/conftest.py                # home_with_projects builds real-shape registry
installer/tests/migrations/test_sql_only_runner.py        # update fixtures
plugins/proj/server/tests/test_schema_version.py          # update fixtures
plugins/proj/server/tests/test_schema_version_require_*.py # update fixtures

installer/tests/migrations/test_load_project_list.py      # NEW — 4 tests for the registry-reader
```

**Data model:**

```
~/.claude/proj.yaml                                # global config (UNCHANGED)
  tracking_dir: ~/projects/tracking
  ...

~/projects/tracking/active-projects.yaml            # registry (UNCHANGED — proj plugin owns)
  projects:
    cpm:
      name: cpm
      tracking_dir: /home/raul/projects/tracking/cpm
      archived: false
      ...

~/projects/tracking/cpm/                           # per-project dir (proj plugin owns)
  data.db                                          # SQL store
  meta.yaml                                        # derived from sql_meta (UNCHANGED)
  todos.yaml + archive.yaml + decisions.yaml      # YAML hybrid (only on v1/v2)
  .schema-version                                  # NEW — single-line int (1, 2, or 3)
```

## 4. `load_project_list()` rewrite

```python
def load_project_list() -> list[dict]:
    """Return projects to consider for migration as [{"name", "path"}, ...].

    Reads the proj plugin's project registry at <tracking_dir>/active-projects.yaml.
    Filters out archived projects. Returns empty list when registry is missing
    (fresh install, no projects yet).
    """
    config_path = Path.home() / ".claude" / "proj.yaml"
    if not config_path.exists():
        return []
    try:
        cfg = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return []
    tracking_dir = Path(cfg.get("tracking_dir") or "~/projects/tracking").expanduser()
    registry_path = tracking_dir / "active-projects.yaml"
    if not registry_path.exists():
        return []
    try:
        registry = yaml.safe_load(registry_path.read_text()) or {}
    except yaml.YAMLError:
        return []
    projects_map = registry.get("projects") or {}
    out: list[dict] = []
    for name, entry in projects_map.items():
        if entry.get("archived", False):
            continue
        path = entry.get("tracking_dir") or str(tracking_dir / name)
        out.append({"name": name, "path": path})
    return out
```

## 5. `schema_version.py` rewrite (proj plugin)

```python
SCHEMA_VERSION_FILE = ".schema-version"


def _schema_version_path(cfg: ProjConfig, project_name: str) -> Path:
    return Path(cfg.tracking_dir).expanduser() / project_name / SCHEMA_VERSION_FILE


def current(cfg: ProjConfig, project_name: str) -> int:
    """Return the per-project schema_version. File absent / unreadable → 1."""
    path = _schema_version_path(cfg, project_name)
    try:
        raw = path.read_text().strip()
    except (FileNotFoundError, OSError):
        return 1
    try:
        return int(raw)
    except (TypeError, ValueError):
        log.warning("%s contains malformed value %r; treating as 1", path, raw)
        return 1


def bump_schema_version(project_dir: Path, version: int) -> None:
    """Write the schema_version file atomically (temp+rename)."""
    path = project_dir / SCHEMA_VERSION_FILE
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(f"{version}\n")
    tmp.replace(path)
```

The `require_flat` / `require_current` functions stay — they just use the new `current()` under the hood.

## 6. `installer/migrations/detect.py` rewrite

`read_schema_version(path: Path)` becomes the single-file reader for `.schema-version`. `bump_schema_version(project_dir: Path, version: int)` writes the file.

`discover_pending` updated to look at `.schema-version` instead of `proj.yaml`. Returns `PendingProject` with `schema_version_path` instead of `proj_yaml_path`.

`detect_already_flat` unchanged (reads todos.yaml / data.db, not version file).

## 7. PendingProject field rename

```python
@dataclass(frozen=True)
class PendingProject:
    name: str
    path: Path
    schema_version_path: Path  # was: proj_yaml_path
    current_version: int
```

Update all consumers:
- `flat_todo.py::FlatTodoMigration._commit` — calls `bump_schema_version(self.project.path, 2)` (writes to project dir, not a yaml file)
- `sql_only.py::SqlOnlyMigration._commit` — same, but with version=3
- E2E test fixtures — adjust how they construct PendingProject

## 8. Test rewrites

### 8.1 New tests (4)

`installer/tests/migrations/test_load_project_list.py`:
- `test_load_returns_projects_from_registry` — writes a fixture active-projects.yaml + global proj.yaml, asserts list contents
- `test_load_skips_archived_projects` — registry has 2 projects, one archived; only 1 returned
- `test_load_returns_empty_when_global_config_missing`
- `test_load_returns_empty_when_registry_missing`

### 8.2 Fixture rewrites

`installer/tests/migrations/conftest.py::tmp_project`:
```python
@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project dir with .schema-version=1 (legacy) + YAML data."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".schema-version").write_text("1\n")
    (root / "todos.yaml").write_text("[]\n")
    (root / "archive.yaml").write_text("[]\n")
    return root
```

`installer/tests/migrations/e2e/conftest.py::home_with_projects` — write a real-shape `active-projects.yaml` registry + `.schema-version` files (omit for v1, write `1` explicitly for clarity).

`installer/tests/migrations/test_detect.py` — replace all `proj.yaml` writes with `.schema-version` text writes.

`plugins/proj/server/tests/test_schema_version*.py` — same.

`installer/tests/migrations/test_cli_flags.py::test_dry_run_flag_exits_zero_without_mutation` — set up a real-shape registry so the dry-run path actually iterates projects.

### 8.3 Update existing assertions

Tests that asserted `proj_yaml_path` on `PendingProject` need to assert `schema_version_path` instead.

## 9. Verification

After merge, manual smoke test:
```
$ cpm-install --migrate-dry-run
Dry-run report: ~/.claude/migrations/<ts>/dry-run.md

$ cat ~/.claude/migrations/<ts>/dry-run.md
# Flat-Todo Migration — Dry Run
Run timestamp: ...

## cpm
- Path: /home/raul/projects/tracking/cpm
- Schema version: 1 → 2 (and 2 → 3 chained)
- Parents: <count>
- Children: <count>
...
```

Non-empty report = fix verified.

## 10. Out of scope

- Migrating `meta.yaml` to SQL-only (still derived; 647's scope; doesn't affect schema_version mechanics)
- Reworking the `tracking_dir` config layout (still in global proj.yaml)
- Any wizard UI changes (the screens render whatever discover_pending returns)

## 11. Risks

- **Existing test fixtures**: many tests use `proj.yaml` synthetic fixtures. Sweep + update is mechanical but broad (~30 tests). Diligent grep needed to catch all sites.
- **PendingProject field rename**: any code referencing `proj_yaml_path` will break. Grep + fix is the safety net.
- **Backward compatibility**: pre-existing v1 projects have NO `.schema-version` file. `current()` returns 1 (the legacy default). Migration writes the file as part of the v1→v2 commit phase. No special bootstrap needed.
- **Registry race**: if proj plugin updates `active-projects.yaml` while wizard is reading it, results are stale. Wizard reads once at start of run; migrations do not re-read mid-run. Acceptable.

## 12. Follow-up todos

- None anticipated. The fix is self-contained.
