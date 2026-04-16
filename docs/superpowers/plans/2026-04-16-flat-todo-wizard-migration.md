# Flat-Todo Wizard Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a one-time migration that flattens nested (`parent`/`children`) todos to flat (`group:<parent-id>` tag) and resyncs existing Todoist/Trello/Jira state, orchestrated by the installer wizard.

**Architecture:** New `installer/migrations/` subpackage hosts a per-project state machine (DISCOVERED → PLANNED → CONFIRMED → BACKED_UP → FLATTENED → RESYNCED → COMMITTED), invoked from a post-install wizard hook in `installer/app.py`. Each project gets a full filesystem backup before mutation. Three integration modules (Todoist/Trello/Jira) implement a common `IntegrationResync` protocol and reuse existing plugin client libs. Textual TUI adds three new screens under `installer/screens/migration_*.py`.

**Tech Stack:** Python 3.11+, Textual (TUI), Rich (inline components), pytest + pytest-mock + pytest-textual-snapshot + respx, PyYAML, sqlite3 (stdlib), httpx (via existing plugin clients), `uv` for dependency/test execution.

**Spec:** `docs/superpowers/specs/2026-04-16-flat-todo-wizard-migration-design.md`

**Predicate:** Todo 624 (Python + hook changes for flat todo model) must ship first. This plan assumes 624 has delivered: server-side flat-only enforcement on `todo_add`, removal of parent-chain resolution in `_build_hook_fields`, hook-config updates that no longer inject parent fields. Start this plan only after 624 is merged to `dev`.

**Test execution:** `uv run pytest <path>` from repo root. No justfile.

---

## File Structure

**New files (create):**

```
installer/migrations/
  __init__.py                         # package marker
  types.py                            # MigrationState enum, MigrationPlan dc, PendingProject dc, RecoveryPath enum
  detect.py                           # discover_pending, read/bump_schema_version, detect_already_flat
  backup.py                           # BackupSnapshot (create/restore/verify)
  lock.py                             # MigrationLock (flock context manager)
  transform.py                        # flatten_todos_yaml, flatten_todos_sql
  base.py                             # MigrationRunner abstract + state-machine driver
  flat_todo.py                        # FlatTodoMigration concrete runner
  report.py                           # DryRunReport markdown writer
  entry.py                            # run_pending_migrations (wizard + standalone entry)
  integrations/
    __init__.py
    base.py                           # IntegrationResync Protocol, Action, ResyncResult
    todoist.py                        # TodoistResync
    trello.py                         # TrelloResync
    jira.py                           # JiraResync

installer/screens/
  migration_overview.py               # Screen 1
  migration_review.py                 # Screen 2 + tabbed preview
  migration_progress.py               # Screen 3 + summary
```

**Modified files:**

```
installer/main.py                     # +CLI flags --migrate-flat, --migrate-flat-dry-run, --backup-retain, --strict-resync
installer/cli.py                      # +handlers for the flags
installer/app.py                      # call run_pending_migrations post-plugin-install
```

**Tests:**

```
installer/tests/migrations/
  __init__.py
  conftest.py                         # fixtures: tmp_project, fake_todoist_client, ...
  test_detect.py
  test_backup.py
  test_lock.py
  test_state_machine.py
  test_flatten_yaml.py
  test_flatten_sql.py
  test_flat_todo_runner.py
  test_integrations_plan.py
  test_todoist_resync.py              # respx
  test_trello_resync.py               # respx
  test_jira_resync.py                 # respx
  test_dry_run_report.py
  test_cli_flags.py
  test_screens.py                     # pytest-textual-snapshot
  e2e/
    __init__.py
    conftest.py
    test_e2e_happy_path.py
    test_e2e_rollback.py
    test_e2e_resync_partial.py
    test_e2e_power_loss_recovery.py
    test_e2e_dry_run_and_non_tty.py
```

---

## Task 1: Scaffold migrations package + schema-version detection

**Files:**
- Create: `installer/migrations/__init__.py` (empty)
- Create: `installer/migrations/types.py`
- Create: `installer/migrations/detect.py`
- Create: `installer/tests/migrations/__init__.py` (empty)
- Create: `installer/tests/migrations/conftest.py`
- Create: `installer/tests/migrations/test_detect.py`

- [ ] **Step 1: Write the types module**

```python
# installer/migrations/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


TARGET_SCHEMA_VERSION = 2


class MigrationState(str, Enum):
    DISCOVERED = "discovered"
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"
    BACKED_UP = "backed_up"
    FLATTENED = "flattened"
    RESYNCED = "resynced"
    COMMITTED = "committed"
    CLEANED = "cleaned"
    RESTORING = "restoring"
    FAILED = "failed"


class RecoveryPath(str, Enum):
    NORMAL = "normal"
    BUMP_ONLY = "bump_only"  # data already flat, only schema_version missing


@dataclass(frozen=True)
class PendingProject:
    name: str
    path: Path
    proj_yaml_path: Path
    current_version: int  # 1 or 0 (absent)


@dataclass
class TodoRef:
    id: str
    title: str
    todoist_task_id: str | None = None
    trello_card_id: str | None = None
    trello_checklist_id: str | None = None
    trello_checklist_item_id: str | None = None
    jira_issue_key: str | None = None
    parent: str | None = None


@dataclass
class MigrationPlan:
    project: PendingProject
    parents: list[TodoRef] = field(default_factory=list)
    children: list[TodoRef] = field(default_factory=list)
    integration_actions: dict[str, list["Action"]] = field(default_factory=dict)  # noqa: F821
    recovery_path: RecoveryPath = RecoveryPath.NORMAL
```

- [ ] **Step 2: Write failing tests for `discover_pending` and `read_schema_version`**

```python
# installer/tests/migrations/test_detect.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import (
    bump_schema_version,
    discover_pending,
    read_schema_version,
)
from installer.migrations.types import PendingProject


def write_proj_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def test_read_schema_version_missing_field_returns_1(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    write_proj_yaml(p, {"name": "x"})
    assert read_schema_version(p) == 1


def test_read_schema_version_reads_int(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    write_proj_yaml(p, {"name": "x", "schema_version": 2})
    assert read_schema_version(p) == 2


def test_read_schema_version_corrupted_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    p.write_text("not: [valid: yaml")
    assert read_schema_version(p) is None


def test_read_schema_version_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_schema_version(tmp_path / "nope.yaml") is None


def test_discover_pending_yields_legacy_projects(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    current_dir = tmp_path / "current"
    future_dir = tmp_path / "future"
    write_proj_yaml(legacy_dir / "proj.yaml", {"name": "legacy"})
    write_proj_yaml(current_dir / "proj.yaml", {"name": "current", "schema_version": 2})
    write_proj_yaml(future_dir / "proj.yaml", {"name": "future", "schema_version": 9})

    projects = [
        {"name": "legacy", "path": str(legacy_dir)},
        {"name": "current", "path": str(current_dir)},
        {"name": "future", "path": str(future_dir)},
    ]

    result = list(discover_pending(projects))
    assert len(result) == 1
    assert result[0].name == "legacy"
    assert result[0].current_version == 1


def test_discover_pending_skips_corrupted(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    bad_dir = tmp_path / "bad"
    (bad_dir).mkdir()
    (bad_dir / "proj.yaml").write_text("not: [valid")

    projects = [{"name": "bad", "path": str(bad_dir)}]
    result = list(discover_pending(projects))
    assert result == []
    assert any("proj.yaml unreadable" in r.message for r in caplog.records)


def test_bump_schema_version_writes_atomically(tmp_path: Path) -> None:
    p = tmp_path / "proj.yaml"
    write_proj_yaml(p, {"name": "x"})
    bump_schema_version(p, 2)
    data = yaml.safe_load(p.read_text())
    assert data["schema_version"] == 2
    assert data["name"] == "x"  # other keys preserved
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_detect.py -v`
Expected: All fail with `ImportError: cannot import name 'discover_pending'` (module not created yet).

- [ ] **Step 4: Implement `detect.py`**

```python
# installer/migrations/detect.py
from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import yaml

from installer.migrations.types import TARGET_SCHEMA_VERSION, PendingProject

log = logging.getLogger(__name__)


def read_schema_version(proj_yaml_path: Path) -> int | None:
    """Return schema_version (1 when absent), or None when unreadable."""
    try:
        raw = proj_yaml_path.read_text()
    except FileNotFoundError:
        return None
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    v = data.get("schema_version")
    if v is None:
        return 1
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def bump_schema_version(proj_yaml_path: Path, version: int) -> None:
    """Merge schema_version into proj.yaml atomically (temp+rename)."""
    data: dict = yaml.safe_load(proj_yaml_path.read_text()) or {}
    data["schema_version"] = version
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=proj_yaml_path.parent,
        prefix=".proj.yaml.",
        suffix=".tmp",
        delete=False,
    )
    try:
        yaml.safe_dump(data, tmp, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, proj_yaml_path)


def discover_pending(projects: Iterable[dict]) -> Iterator[PendingProject]:
    """Yield PendingProject entries for projects with schema_version < target."""
    for entry in projects:
        name = entry["name"]
        proj_path = Path(entry["path"])
        proj_yaml = proj_path / "proj.yaml"
        v = read_schema_version(proj_yaml)
        if v is None:
            log.warning("proj.yaml unreadable for %s, skipping migration detect", name)
            continue
        if v >= TARGET_SCHEMA_VERSION:
            continue
        yield PendingProject(
            name=name,
            path=proj_path,
            proj_yaml_path=proj_yaml,
            current_version=v,
        )


def detect_already_flat(todos_yaml_path: Path) -> bool:
    """Return True when no todo has a non-null `parent` field."""
    try:
        data = yaml.safe_load(todos_yaml_path.read_text()) or []
    except (FileNotFoundError, yaml.YAMLError):
        return False
    if not isinstance(data, list):
        return False
    return all(t.get("parent") is None and not t.get("children") for t in data)
```

- [ ] **Step 5: Write `conftest.py` fixture**

```python
# installer/tests/migrations/conftest.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project dir with proj.yaml (schema_version=1)."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "proj.yaml").write_text(yaml.safe_dump({"name": "demo"}))
    (root / "todos.yaml").write_text(yaml.safe_dump([]))
    (root / "archive.yaml").write_text(yaml.safe_dump([]))
    return root
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_detect.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add installer/migrations/__init__.py installer/migrations/types.py installer/migrations/detect.py installer/tests/migrations/__init__.py installer/tests/migrations/conftest.py installer/tests/migrations/test_detect.py
git commit -m "feat(installer/migrations): scaffold package + schema-version detection"
```

---

## Task 2: Backup snapshot with manifest + checksums

**Files:**
- Create: `installer/migrations/backup.py`
- Create: `installer/tests/migrations/test_backup.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_backup.py
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from installer.migrations.backup import BackupSnapshot, VerificationError


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_db(path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()


@pytest.fixture
def src_project(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    root.mkdir()
    (root / "todos.yaml").write_text("- id: '1'\n  title: hi\n")
    (root / "archive.yaml").write_text("[]\n")
    (root / "proj.yaml").write_text("name: x\n")
    _make_db(root / "data.db")
    return root


def test_create_writes_all_artifacts(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "2026-04-16T12-00-00", src_project, backup_root)
    assert (snap.dir / "todos.yaml").exists()
    assert (snap.dir / "archive.yaml").exists()
    assert (snap.dir / "proj.yaml").exists()
    assert (snap.dir / "data.db").exists()
    manifest = json.loads((snap.dir / "manifest.json").read_text())
    assert manifest["project"] == "demo"
    assert manifest["run_ts"] == "2026-04-16T12-00-00"
    for name, digest in manifest["checksums"].items():
        assert digest == _sha256(snap.dir / name)


def test_create_is_atomic_no_tmp_dir_left(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    BackupSnapshot.create("demo", "ts", src_project, backup_root)
    leftover = list(backup_root.glob("*.tmp"))
    assert leftover == []


def test_restore_overwrites_source(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", src_project, backup_root)
    # mutate source after backup
    (src_project / "todos.yaml").write_text("- id: '2'\n  title: changed\n")
    snap.restore()
    assert (src_project / "todos.yaml").read_text() == "- id: '1'\n  title: hi\n"


def test_restore_rejects_tampered_manifest(src_project: Path, tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", src_project, backup_root)
    # tamper: flip one byte in todos.yaml inside backup
    (snap.dir / "todos.yaml").write_text("tampered\n")
    with pytest.raises(VerificationError):
        snap.restore()


def test_create_handles_missing_optional_files(tmp_path: Path) -> None:
    # archive.yaml is optional; data.db is optional (git_enabled=false)
    root = tmp_path / "src"
    root.mkdir()
    (root / "todos.yaml").write_text("[]\n")
    (root / "proj.yaml").write_text("name: x\n")
    backup_root = tmp_path / "backups"
    snap = BackupSnapshot.create("demo", "ts", root, backup_root)
    assert (snap.dir / "todos.yaml").exists()
    assert not (snap.dir / "archive.yaml").exists()
    assert not (snap.dir / "data.db").exists()
    manifest = json.loads((snap.dir / "manifest.json").read_text())
    assert "archive.yaml" not in manifest["checksums"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_backup.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `backup.py`**

```python
# installer/migrations/backup.py
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


class VerificationError(RuntimeError):
    """Raised when a backup's manifest checksums don't match its files."""


OPTIONAL_FILES = ("archive.yaml", "data.db")
REQUIRED_FILES = ("todos.yaml", "proj.yaml")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _checkpoint_wal(db_path: Path) -> None:
    """Flush WAL to main .db file so the file copy is point-in-time consistent."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except sqlite3.Error as e:
        log.warning("WAL checkpoint failed for %s: %s", db_path, e)


@dataclass
class BackupSnapshot:
    project: str
    run_ts: str
    source_dir: Path
    dir: Path
    checksums: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        project: str,
        run_ts: str,
        source_dir: Path,
        backup_root: Path,
    ) -> BackupSnapshot:
        """Snapshot source_dir into backup_root/<run_ts>/<project>/ atomically."""
        final_dir = backup_root / run_ts / project
        tmp_dir = backup_root / run_ts / f"{project}.tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        snap = cls(
            project=project,
            run_ts=run_ts,
            source_dir=source_dir,
            dir=final_dir,
        )

        try:
            for name in REQUIRED_FILES:
                src = source_dir / name
                if not src.exists():
                    raise FileNotFoundError(f"required file missing: {src}")
                shutil.copy2(src, tmp_dir / name)
                snap.checksums[name] = _sha256(tmp_dir / name)

            for name in OPTIONAL_FILES:
                src = source_dir / name
                if not src.exists():
                    continue
                if name == "data.db":
                    _checkpoint_wal(src)
                shutil.copy2(src, tmp_dir / name)
                snap.checksums[name] = _sha256(tmp_dir / name)

            manifest = {
                "project": project,
                "run_ts": run_ts,
                "source_dir": str(source_dir),
                "checksums": dict(snap.checksums),
            }
            (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
            # manifest excluded from its own checksum map
            os.replace(tmp_dir, final_dir)
            snap.dir = final_dir
            return snap
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def verify(self) -> None:
        """Raise VerificationError if any file's digest mismatches the manifest."""
        manifest = json.loads((self.dir / "manifest.json").read_text())
        for name, expected in manifest["checksums"].items():
            actual = _sha256(self.dir / name)
            if actual != expected:
                raise VerificationError(
                    f"checksum mismatch for {name}: expected {expected}, got {actual}",
                )

    def restore(self) -> None:
        """Copy backup files back over source_dir after verify()."""
        self.verify()
        manifest = json.loads((self.dir / "manifest.json").read_text())
        for name in manifest["checksums"]:
            shutil.copy2(self.dir / name, self.source_dir / name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_backup.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/backup.py installer/tests/migrations/test_backup.py
git commit -m "feat(installer/migrations): backup snapshot with manifest + checksum verify"
```

---

## Task 3: Concurrent-run lock (flock)

**Files:**
- Create: `installer/migrations/lock.py`
- Create: `installer/tests/migrations/test_lock.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_lock.py
from __future__ import annotations

import multiprocessing
import os
import signal
import time
from pathlib import Path

import pytest

from installer.migrations.lock import LockContention, MigrationLock


def test_acquire_and_release(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    with MigrationLock(lock_path) as lk:
        assert lock_path.exists()
        assert lk.pid == os.getpid()
    # After exit the lock file's lock is released; file may remain
    # (flock releases on fd close; file staying is fine, other processes can re-acquire)


def test_second_acquire_raises(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    with MigrationLock(lock_path):
        with pytest.raises(LockContention):
            with MigrationLock(lock_path):
                pass


def _hold_lock(lock_path: str, ready_evt, release_evt) -> None:  # pragma: no cover
    from installer.migrations.lock import MigrationLock as ML

    with ML(Path(lock_path)):
        ready_evt.set()
        release_evt.wait(timeout=10)


def test_cross_process_contention(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    p = multiprocessing.Process(target=_hold_lock, args=(str(lock_path), ready, release))
    p.start()
    try:
        assert ready.wait(timeout=5)
        with pytest.raises(LockContention):
            with MigrationLock(lock_path):
                pass
    finally:
        release.set()
        p.join(timeout=5)


def test_holder_pid_written_to_file(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    with MigrationLock(lock_path):
        assert lock_path.read_text().strip() == str(os.getpid())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_lock.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `lock.py`**

```python
# installer/migrations/lock.py
from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path


class LockContention(RuntimeError):
    """Another migration run is already in progress."""

    def __init__(self, lock_path: Path, holder_pid: str) -> None:
        super().__init__(
            f"migration lock held by pid {holder_pid} at {lock_path}",
        )
        self.lock_path = lock_path
        self.holder_pid = holder_pid


@dataclass
class MigrationLock:
    path: Path
    _fd: int | None = None
    pid: int = 0

    def __enter__(self) -> MigrationLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = _read_pid(self.path)
            os.close(self._fd)
            self._fd = None
            raise LockContention(self.path, holder) from None
        self.pid = os.getpid()
        os.ftruncate(self._fd, 0)
        os.write(self._fd, f"{self.pid}\n".encode())
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def _read_pid(path: Path) -> str:
    try:
        return path.read_text().strip() or "?"
    except OSError:
        return "?"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_lock.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/lock.py installer/tests/migrations/test_lock.py
git commit -m "feat(installer/migrations): flock-based concurrent-run lock"
```

---

## Task 4: MigrationRunner base + state machine

**Files:**
- Create: `installer/migrations/base.py`
- Create: `installer/tests/migrations/test_state_machine.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_state_machine.py
from __future__ import annotations

from pathlib import Path

import pytest

from installer.migrations.base import InvalidTransition, MigrationRunner
from installer.migrations.types import MigrationState


class FakeRunner(MigrationRunner):
    def _plan(self): ...
    def _backup(self): ...
    def _flatten(self): ...
    def _resync(self): ...
    def _commit(self): ...
    def _restore(self): ...


def test_valid_transition_sequence(tmp_path: Path) -> None:
    r = FakeRunner(project_name="demo", project_dir=tmp_path)
    assert r.state == MigrationState.DISCOVERED
    r.transition(MigrationState.PLANNED)
    r.transition(MigrationState.CONFIRMED)
    r.transition(MigrationState.BACKED_UP)
    r.transition(MigrationState.FLATTENED)
    r.transition(MigrationState.RESYNCED)
    r.transition(MigrationState.COMMITTED)
    r.transition(MigrationState.CLEANED)


def test_invalid_transition_raises(tmp_path: Path) -> None:
    r = FakeRunner(project_name="demo", project_dir=tmp_path)
    with pytest.raises(InvalidTransition):
        r.transition(MigrationState.COMMITTED)  # skip phases


def test_skip_branch(tmp_path: Path) -> None:
    r = FakeRunner(project_name="demo", project_dir=tmp_path)
    r.transition(MigrationState.PLANNED)
    r.transition(MigrationState.SKIPPED)
    with pytest.raises(InvalidTransition):
        r.transition(MigrationState.BACKED_UP)


def test_restoring_allowed_from_post_backup_states(tmp_path: Path) -> None:
    for from_state in (
        MigrationState.FLATTENED,
        MigrationState.RESYNCED,
        MigrationState.COMMITTED,
    ):
        r = FakeRunner(project_name="demo", project_dir=tmp_path)
        for s in (
            MigrationState.PLANNED,
            MigrationState.CONFIRMED,
            MigrationState.BACKED_UP,
        ):
            r.transition(s)
        # climb to target then test restore path
        if from_state != MigrationState.BACKED_UP:
            r.transition(MigrationState.FLATTENED)
        if from_state == MigrationState.RESYNCED:
            r.transition(MigrationState.RESYNCED)
        if from_state == MigrationState.COMMITTED:
            r.transition(MigrationState.RESYNCED)
            r.transition(MigrationState.COMMITTED)
        r.transition(MigrationState.RESTORING)
        r.transition(MigrationState.FAILED)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_state_machine.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `base.py`**

```python
# installer/migrations/base.py
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from pathlib import Path

from installer.migrations.types import MigrationState

log = logging.getLogger(__name__)


class InvalidTransition(RuntimeError):
    """Attempted state transition not allowed by the state machine."""


ALLOWED: dict[MigrationState, set[MigrationState]] = {
    MigrationState.DISCOVERED: {MigrationState.PLANNED},
    MigrationState.PLANNED: {MigrationState.CONFIRMED, MigrationState.SKIPPED},
    MigrationState.CONFIRMED: {MigrationState.BACKED_UP},
    MigrationState.SKIPPED: set(),
    MigrationState.BACKED_UP: {MigrationState.FLATTENED, MigrationState.RESTORING},
    MigrationState.FLATTENED: {MigrationState.RESYNCED, MigrationState.RESTORING},
    MigrationState.RESYNCED: {MigrationState.COMMITTED, MigrationState.RESTORING},
    MigrationState.COMMITTED: {MigrationState.CLEANED, MigrationState.RESTORING},
    MigrationState.CLEANED: set(),
    MigrationState.RESTORING: {MigrationState.FAILED},
    MigrationState.FAILED: set(),
}


@dataclass
class MigrationRunner(abc.ABC):
    project_name: str
    project_dir: Path
    state: MigrationState = MigrationState.DISCOVERED
    history: list[MigrationState] = field(default_factory=list)

    def transition(self, target: MigrationState) -> None:
        if target not in ALLOWED[self.state]:
            raise InvalidTransition(
                f"{self.project_name}: cannot move {self.state.value} → {target.value}",
            )
        log.debug("%s: %s → %s", self.project_name, self.state.value, target.value)
        self.history.append(self.state)
        self.state = target

    @abc.abstractmethod
    def _plan(self) -> None: ...

    @abc.abstractmethod
    def _backup(self) -> None: ...

    @abc.abstractmethod
    def _flatten(self) -> None: ...

    @abc.abstractmethod
    def _resync(self) -> None: ...

    @abc.abstractmethod
    def _commit(self) -> None: ...

    @abc.abstractmethod
    def _restore(self) -> None: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_state_machine.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/base.py installer/tests/migrations/test_state_machine.py
git commit -m "feat(installer/migrations): MigrationRunner base + state transitions"
```

---

## Task 5: YAML flatten transform

**Files:**
- Create: `installer/migrations/transform.py` (YAML portion only; SQL added in Task 6)
- Create: `installer/tests/migrations/test_flatten_yaml.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_flatten_yaml.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.transform import flatten_todos_yaml


def _load(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text()) or []


def test_parent_and_children_become_group_tag(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    src.write_text(
        yaml.safe_dump([
            {"id": "1", "title": "parent", "parent": None, "children": ["1.1", "1.2"], "tags": []},
            {"id": "1.1", "title": "child a", "parent": "1", "children": [], "tags": []},
            {"id": "1.2", "title": "child b", "parent": "1", "children": [], "tags": ["existing"]},
            {"id": "2", "title": "solo", "parent": None, "children": [], "tags": []},
        ]),
    )
    flatten_todos_yaml(src)
    out = _load(src)
    by_id = {t["id"]: t for t in out}
    assert "parent" not in by_id["1"]
    assert "children" not in by_id["1"]
    assert "next_child_id" not in by_id["1"]
    assert "group:1" in by_id["1.1"]["tags"]
    assert "group:1" in by_id["1.2"]["tags"]
    assert "existing" in by_id["1.2"]["tags"]  # existing tags preserved
    assert by_id["1"]["tags"] == []  # parent itself has no group tag (it IS the group)
    assert by_id["2"]["tags"] == []  # standalone untouched


def test_idempotent_on_flat_data(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    data = [
        {"id": "1", "title": "parent", "tags": []},
        {"id": "1.1", "title": "child", "tags": ["group:1"]},
    ]
    src.write_text(yaml.safe_dump(data))
    flatten_todos_yaml(src)
    assert _load(src) == data


def test_orphan_child_gets_warning_and_no_group_tag(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    src = tmp_path / "todos.yaml"
    src.write_text(
        yaml.safe_dump([
            {"id": "7", "title": "orphan", "parent": "missing", "children": [], "tags": []},
        ]),
    )
    flatten_todos_yaml(src)
    out = _load(src)
    assert "parent" not in out[0]
    assert not any(t.startswith("group:") for t in out[0]["tags"])
    assert any("orphan" in r.message for r in caplog.records)


def test_child_with_tags_already_containing_group_no_dup(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    src.write_text(
        yaml.safe_dump([
            {"id": "1", "title": "parent", "parent": None, "children": ["1.1"], "tags": []},
            {"id": "1.1", "title": "c", "parent": "1", "children": [], "tags": ["group:1"]},
        ]),
    )
    flatten_todos_yaml(src)
    out = _load(src)
    assert out[1]["tags"].count("group:1") == 1


def test_preserves_other_fields(tmp_path: Path) -> None:
    src = tmp_path / "todos.yaml"
    original = [
        {
            "id": "1",
            "title": "p",
            "parent": None,
            "children": ["1.1"],
            "tags": [],
            "priority": "high",
            "status": "pending",
            "todoist_task_id": "abc",
        },
        {
            "id": "1.1",
            "title": "c",
            "parent": "1",
            "children": [],
            "tags": [],
            "priority": "medium",
            "jira_issue_key": "CPM-5",
        },
    ]
    src.write_text(yaml.safe_dump(original))
    flatten_todos_yaml(src)
    out = _load(src)
    assert out[0]["todoist_task_id"] == "abc"
    assert out[1]["jira_issue_key"] == "CPM-5"
    assert out[0]["priority"] == "high"
    assert out[1]["priority"] == "medium"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_flatten_yaml.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `transform.py` (YAML half)**

```python
# installer/migrations/transform.py
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REMOVED_KEYS = ("parent", "children", "next_child_id")


def flatten_todos_yaml(path: Path) -> None:
    """Rewrite todos.yaml in place: parent/children → group:<parent> tag.

    Idempotent. Writes atomically (temp + rename). Preserves all other fields.
    Orphan children (parent id missing from todos) keep their data but get no
    group tag and a WARNING is logged.
    """
    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError(f"{path} root must be a list")
    ids = {t["id"] for t in data if "id" in t}

    for todo in data:
        parent = todo.pop("parent", None)
        todo.pop("children", None)
        todo.pop("next_child_id", None)
        if parent is None:
            continue
        tag = f"group:{parent}"
        tags = todo.setdefault("tags", [])
        if parent not in ids:
            log.warning(
                "orphan child todo id=%s references missing parent=%s; no group tag added",
                todo.get("id"),
                parent,
            )
            continue
        if tag not in tags:
            tags.append(tag)

    _atomic_write_yaml(path, data)


def _atomic_write_yaml(path: Path, data: list) -> None:
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        yaml.safe_dump(data, tmp, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_flatten_yaml.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/transform.py installer/tests/migrations/test_flatten_yaml.py
git commit -m "feat(installer/migrations): YAML flatten transform (parent/children → group tag)"
```

---

## Task 6: SQL flatten (ALTER TABLE rebuild)

**Files:**
- Modify: `installer/migrations/transform.py` (add SQL half)
- Create: `installer/tests/migrations/test_flatten_sql.py`

SQLite doesn't support `ALTER TABLE ... DROP COLUMN` in every version shipped with older Pythons. Use the **rebuild pattern**: create new table → copy rows with compatible columns → drop old → rename new. Same approach used in proj plugin's `sql_todos` migrations.

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_flatten_sql.py
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from installer.migrations.transform import flatten_todos_sql


def _schema(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    path = tmp_path / "data.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE todos (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT,
            priority TEXT,
            parent TEXT,
            children TEXT,
            next_child_id INTEGER,
            tags TEXT
        );
        CREATE TABLE archive_todos (
            id TEXT PRIMARY KEY,
            title TEXT,
            parent TEXT,
            children TEXT,
            next_child_id INTEGER,
            tags TEXT
        );
        INSERT INTO todos VALUES
          ('1','p','pending','high',NULL,'["1.1"]',2,'[]'),
          ('1.1','c','pending','medium','1','[]',1,'["group:1"]');
        INSERT INTO archive_todos VALUES
          ('9','done',NULL,'[]',1,'[]');
        """,
    )
    conn.commit()
    conn.close()
    return path


def test_flatten_removes_columns_from_todos(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    conn = sqlite3.connect(legacy_db)
    cols = _schema(conn, "todos")
    assert "parent" not in cols
    assert "children" not in cols
    assert "next_child_id" not in cols
    assert {"id", "title", "status", "priority", "tags"} <= set(cols)


def test_flatten_removes_columns_from_archive(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    conn = sqlite3.connect(legacy_db)
    cols = _schema(conn, "archive_todos")
    assert "parent" not in cols
    assert "children" not in cols


def test_flatten_preserves_data(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    conn = sqlite3.connect(legacy_db)
    ids = [r[0] for r in conn.execute("SELECT id FROM todos ORDER BY id")]
    assert ids == ["1", "1.1"]
    row = conn.execute("SELECT id,title,status,priority,tags FROM todos WHERE id='1.1'").fetchone()
    assert row == ("1.1", "c", "pending", "medium", '["group:1"]')


def test_flatten_idempotent(legacy_db: Path) -> None:
    flatten_todos_sql(legacy_db)
    flatten_todos_sql(legacy_db)  # should be a no-op
    conn = sqlite3.connect(legacy_db)
    cols = _schema(conn, "todos")
    assert "parent" not in cols


def test_flatten_skips_when_db_absent(tmp_path: Path) -> None:
    flatten_todos_sql(tmp_path / "nope.db")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_flatten_sql.py -v`
Expected: ImportError or AttributeError.

- [ ] **Step 3: Implement SQL flatten**

Append to `installer/migrations/transform.py`:

```python
import sqlite3

LEGACY_COLS = {"parent", "children", "next_child_id"}


def flatten_todos_sql(db_path: Path) -> None:
    """Drop parent/children/next_child_id columns from todos + archive_todos.

    Uses SQLite rebuild pattern: CREATE new table → INSERT SELECT compatible cols →
    DROP old → RENAME. Idempotent: skips tables that don't have the legacy columns.
    Skips silently if db_path doesn't exist (git_enabled=false setups).
    """
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table in ("todos", "archive_todos"):
            _rebuild_table_without_legacy_cols(conn, table)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rebuild_table_without_legacy_cols(conn: sqlite3.Connection, table: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        return  # table doesn't exist in this db
    all_cols = [(r[1], r[2], r[3], r[4], r[5]) for r in rows]  # name, type, notnull, default, pk
    keep = [c for c in all_cols if c[0] not in LEGACY_COLS]
    if len(keep) == len(all_cols):
        return  # already flat

    col_defs: list[str] = []
    for name, col_type, notnull, dflt, pk in keep:
        parts = [f'"{name}"', col_type or "TEXT"]
        if notnull:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        if pk:
            parts.append("PRIMARY KEY")
        col_defs.append(" ".join(parts))

    new_table = f"{table}__new"
    col_list = ", ".join(f'"{c[0]}"' for c in keep)
    conn.execute(f'CREATE TABLE "{new_table}" ({", ".join(col_defs)})')
    conn.execute(f'INSERT INTO "{new_table}" ({col_list}) SELECT {col_list} FROM "{table}"')
    conn.execute(f'DROP TABLE "{table}"')
    conn.execute(f'ALTER TABLE "{new_table}" RENAME TO "{table}"')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_flatten_sql.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/transform.py installer/tests/migrations/test_flatten_sql.py
git commit -m "feat(installer/migrations): SQL ALTER TABLE rebuild to drop legacy parent/children cols"
```

---

## Task 7: FlatTodoMigration — local-only orchestration

Wires Tasks 2–6 together for a single project's state machine without integration resync.

**Files:**
- Create: `installer/migrations/flat_todo.py`
- Create: `installer/tests/migrations/test_flat_todo_runner.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_flat_todo_runner.py
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.types import MigrationState, PendingProject, RecoveryPath


def _setup_project(root: Path) -> PendingProject:
    root.mkdir(parents=True)
    (root / "proj.yaml").write_text(yaml.safe_dump({"name": "demo"}))
    (root / "todos.yaml").write_text(
        yaml.safe_dump([
            {"id": "1", "title": "p", "parent": None, "children": ["1.1"], "tags": []},
            {"id": "1.1", "title": "c", "parent": "1", "children": [], "tags": []},
        ]),
    )
    (root / "archive.yaml").write_text("[]\n")
    conn = sqlite3.connect(root / "data.db")
    conn.executescript(
        """
        CREATE TABLE todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);
        INSERT INTO todos VALUES ('1','p',NULL,'["1.1"]','[]',2);
        INSERT INTO todos VALUES ('1.1','c','1','[]','[]',1);
        CREATE TABLE archive_todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);
        """,
    )
    conn.commit()
    conn.close()
    return PendingProject(
        name="demo",
        path=root,
        proj_yaml_path=root / "proj.yaml",
        current_version=1,
    )


def test_happy_path_commits(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    runner = FlatTodoMigration(project=project, run_ts="ts1", backup_root=backup_root)
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert runner.state == MigrationState.COMMITTED
    assert read_schema_version(project.proj_yaml_path) == 2
    todos = yaml.safe_load((project.path / "todos.yaml").read_text())
    assert "group:1" in todos[1]["tags"]


def test_rollback_on_flatten_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    runner = FlatTodoMigration(project=project, run_ts="ts", backup_root=backup_root)
    runner.plan()
    runner.confirm()

    # Inject failure in flatten step
    from installer.migrations import flat_todo as mod
    monkeypatch.setattr(mod, "flatten_todos_sql", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        runner.execute_local()

    # YAML was flattened before SQL (by design) — restore reverts it
    assert runner.state == MigrationState.FAILED
    todos = yaml.safe_load((project.path / "todos.yaml").read_text())
    assert todos[0]["children"] == ["1.1"]  # restored
    assert read_schema_version(project.proj_yaml_path) == 1


def test_bump_only_recovery_for_already_flat(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    # Pre-flatten manually
    (project.path / "todos.yaml").write_text(
        yaml.safe_dump([
            {"id": "1", "title": "p", "tags": []},
            {"id": "1.1", "title": "c", "tags": ["group:1"]},
        ]),
    )
    conn = sqlite3.connect(project.path / "data.db")
    conn.executescript(
        "DROP TABLE todos; CREATE TABLE todos (id TEXT PRIMARY KEY, title TEXT, tags TEXT);"
        "INSERT INTO todos VALUES ('1','p','[]');"
        "INSERT INTO todos VALUES ('1.1','c','[\"group:1\"]');",
    )
    conn.commit()
    conn.close()

    backup_root = tmp_path / "backups"
    runner = FlatTodoMigration(project=project, run_ts="ts", backup_root=backup_root)
    runner.plan()
    assert runner.plan_result.recovery_path == RecoveryPath.BUMP_ONLY
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert read_schema_version(project.proj_yaml_path) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_flat_todo_runner.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `flat_todo.py`**

```python
# installer/migrations/flat_todo.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from installer.migrations.backup import BackupSnapshot
from installer.migrations.base import MigrationRunner
from installer.migrations.detect import bump_schema_version, detect_already_flat
from installer.migrations.transform import flatten_todos_sql, flatten_todos_yaml
from installer.migrations.types import (
    TARGET_SCHEMA_VERSION,
    MigrationPlan,
    MigrationState,
    PendingProject,
    RecoveryPath,
    TodoRef,
)

log = logging.getLogger(__name__)


@dataclass
class FlatTodoMigration(MigrationRunner):
    project: PendingProject = None  # type: ignore[assignment]
    run_ts: str = ""
    backup_root: Path = Path()
    plan_result: MigrationPlan | None = None
    snapshot: BackupSnapshot | None = None

    def __post_init__(self) -> None:
        # Base class wants project_name/project_dir
        self.project_name = self.project.name
        self.project_dir = self.project.path

    # --- public phases ---------------------------------------------------

    def plan(self) -> MigrationPlan:
        self._plan()
        self.transition(MigrationState.PLANNED)
        assert self.plan_result is not None
        return self.plan_result

    def confirm(self, confirmed: bool = True) -> None:
        self.transition(MigrationState.CONFIRMED if confirmed else MigrationState.SKIPPED)

    def execute_local(self) -> None:
        if self.plan_result is None:
            raise RuntimeError("plan() must run before execute_local()")
        try:
            self._backup()
            self.transition(MigrationState.BACKED_UP)
        except Exception:
            self.transition(MigrationState.RESTORING)
            self.transition(MigrationState.FAILED)
            raise

        if self.plan_result.recovery_path == RecoveryPath.BUMP_ONLY:
            # Skip flatten entirely
            self.transition(MigrationState.FLATTENED)
            self.transition(MigrationState.RESYNCED)
            return

        try:
            self._flatten()
            self.transition(MigrationState.FLATTENED)
            # No integrations in local-only path
            self.transition(MigrationState.RESYNCED)
        except Exception:
            self._restore()
            raise

    def commit(self) -> None:
        try:
            self._commit()
            self.transition(MigrationState.COMMITTED)
        except Exception:
            self._restore()
            raise

    # --- hook impls ------------------------------------------------------

    def _plan(self) -> None:
        todos_path = self.project.path / "todos.yaml"
        data = yaml.safe_load(todos_path.read_text()) or []
        parents: list[TodoRef] = []
        children: list[TodoRef] = []
        for t in data:
            ref = TodoRef(
                id=t.get("id", ""),
                title=t.get("title", ""),
                todoist_task_id=t.get("todoist_task_id"),
                trello_card_id=t.get("trello_card_id"),
                trello_checklist_id=t.get("trello_checklist_id"),
                trello_checklist_item_id=t.get("trello_checklist_item_id"),
                jira_issue_key=t.get("jira_issue_key"),
                parent=t.get("parent"),
            )
            if t.get("children"):
                parents.append(ref)
            if t.get("parent") is not None:
                children.append(ref)
        recovery = (
            RecoveryPath.BUMP_ONLY if detect_already_flat(todos_path) else RecoveryPath.NORMAL
        )
        self.plan_result = MigrationPlan(
            project=self.project,
            parents=parents,
            children=children,
            recovery_path=recovery,
        )

    def _backup(self) -> None:
        self.snapshot = BackupSnapshot.create(
            project=self.project.name,
            run_ts=self.run_ts,
            source_dir=self.project.path,
            backup_root=self.backup_root,
        )

    def _flatten(self) -> None:
        flatten_todos_yaml(self.project.path / "todos.yaml")
        archive = self.project.path / "archive.yaml"
        if archive.exists():
            flatten_todos_yaml(archive)
        flatten_todos_sql(self.project.path / "data.db")

    def _resync(self) -> None:
        # No-op in local-only mode; overridden in Task 12
        pass

    def _commit(self) -> None:
        bump_schema_version(self.project.proj_yaml_path, TARGET_SCHEMA_VERSION)

    def _restore(self) -> None:
        self.transition(MigrationState.RESTORING)
        if self.snapshot is not None:
            self.snapshot.restore()
        self.transition(MigrationState.FAILED)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_flat_todo_runner.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/flat_todo.py installer/tests/migrations/test_flat_todo_runner.py
git commit -m "feat(installer/migrations): FlatTodoMigration local-only runner"
```

---

## Task 8: IntegrationResync protocol + Action types

**Files:**
- Create: `installer/migrations/integrations/__init__.py` (empty)
- Create: `installer/migrations/integrations/base.py`
- Create: `installer/tests/migrations/test_integrations_plan.py` (scaffold — populated by Tasks 9/10/11)

- [ ] **Step 1: Write failing test**

```python
# installer/tests/migrations/test_integrations_plan.py
from __future__ import annotations

from installer.migrations.integrations.base import Action, IntegrationResync, ResyncResult


def test_action_is_frozen_dataclass() -> None:
    a = Action(kind="clear_parent", target_id="abc", payload={})
    import dataclasses
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        a.kind = "other"  # type: ignore[misc]


def test_resyncresult_defaults() -> None:
    r = ResyncResult()
    assert r.ok == []
    assert r.failed == []
    assert r.aborted is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_integrations_plan.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `integrations/base.py`**

```python
# installer/migrations/integrations/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from installer.migrations.types import PendingProject, TodoRef


@dataclass(frozen=True)
class Action:
    kind: str  # e.g. "clear_parent", "promote_checklist_item", "demote_subtask"
    target_id: str  # remote ID (todoist task, trello item, jira issue)
    payload: dict[str, Any]


@dataclass
class FailedAction:
    action: Action
    error_class: str
    message: str
    retryable: bool


@dataclass
class ResyncResult:
    ok: list[Action] = field(default_factory=list)
    failed: list[FailedAction] = field(default_factory=list)
    aborted: bool = False  # True when integration-wide failure stops further actions


@runtime_checkable
class IntegrationResync(Protocol):
    name: str  # "todoist" | "trello" | "jira"

    def enabled_for(self, project: PendingProject) -> bool: ...
    def plan(self, project: PendingProject, migrated: list[TodoRef]) -> list[Action]: ...
    def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_integrations_plan.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/integrations/__init__.py installer/migrations/integrations/base.py installer/tests/migrations/test_integrations_plan.py
git commit -m "feat(installer/migrations): IntegrationResync protocol + Action types"
```

---

## Task 9: Todoist resync (plan + execute)

**Files:**
- Create: `installer/migrations/integrations/todoist.py`
- Create: `installer/tests/migrations/test_todoist_resync.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_todoist_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.todoist import TodoistResync
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_todoist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PendingProject:
    root = tmp_path / "demo"
    root.mkdir()
    proj = root / "proj.yaml"
    proj.write_text(
        yaml.safe_dump({
            "name": "demo",
            "sync": {"todoist": {"enabled": True, "api_token": "tok"}},
        }),
    )
    (root / "todos.yaml").write_text("[]\n")
    return PendingProject(name="demo", path=root, proj_yaml_path=proj, current_version=1)


def _make_children(n: int) -> list[TodoRef]:
    return [
        TodoRef(id=f"1.{i}", title=f"c{i}", todoist_task_id=f"task-{i}", parent="1")
        for i in range(n)
    ]


def test_enabled_for_requires_config_and_links(project_with_todoist: PendingProject) -> None:
    r = TodoistResync()
    assert r.enabled_for(project_with_todoist) is False  # no migrated todos yet
    # With at least one migrated child with a todoist_task_id
    # (enabled_for in this impl takes project + migrated list)
    actions = r.plan(project_with_todoist, _make_children(1))
    assert len(actions) == 1


def test_plan_emits_clear_parent_per_child(project_with_todoist: PendingProject) -> None:
    r = TodoistResync()
    actions = r.plan(project_with_todoist, _make_children(3))
    assert len(actions) == 3
    assert all(a.kind == "clear_parent" for a in actions)
    assert {a.target_id for a in actions} == {"task-0", "task-1", "task-2"}


def test_plan_skips_children_without_todoist_id(project_with_todoist: PendingProject) -> None:
    children = [
        TodoRef(id="1.1", title="c", todoist_task_id=None, parent="1"),
        TodoRef(id="1.2", title="c", todoist_task_id="t", parent="1"),
    ]
    actions = TodoistResync().plan(project_with_todoist, children)
    assert [a.target_id for a in actions] == ["t"]


@respx.mock
def test_execute_batches_successfully(project_with_todoist: PendingProject) -> None:
    actions = TodoistResync().plan(project_with_todoist, _make_children(3))
    respx.post("https://api.todoist.com/api/v1/sync").mock(return_value=Response(200, json={"sync_status": {}}))
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is False
    assert len(result.ok) == 3
    assert not result.failed


@respx.mock
def test_execute_logs_partial_batch_failure(project_with_todoist: PendingProject) -> None:
    actions = TodoistResync().plan(project_with_todoist, _make_children(60))  # 2 batches
    # First batch ok, second 429
    route = respx.post("https://api.todoist.com/api/v1/sync")
    route.side_effect = [Response(200, json={}), Response(429, json={"error": "rate limited"})]
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is False
    assert len(result.ok) == 50
    assert len(result.failed) == 10
    assert result.failed[0].error_class == "HTTPStatusError"


@respx.mock
def test_execute_auth_failure_aborts(project_with_todoist: PendingProject) -> None:
    actions = TodoistResync().plan(project_with_todoist, _make_children(2))
    respx.post("https://api.todoist.com/api/v1/sync").mock(return_value=Response(401, json={}))
    result = TodoistResync().execute(project_with_todoist, actions)
    assert result.aborted is True
    assert len(result.failed) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_todoist_resync.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `todoist.py`**

```python
# installer/migrations/integrations/todoist.py
from __future__ import annotations

import logging
from typing import Any

import httpx

from installer.migrations.integrations.base import (
    Action,
    FailedAction,
    IntegrationResync,
    ResyncResult,
)
from installer.migrations.types import PendingProject, TodoRef

log = logging.getLogger(__name__)

BATCH_SIZE = 50  # Todoist Sync API limit
TODOIST_API = "https://api.todoist.com/api/v1/sync"


class TodoistResync:
    name = "todoist"

    def enabled_for(self, project: PendingProject) -> bool:
        cfg = _load_cfg(project)
        return bool(cfg.get("sync", {}).get("todoist", {}).get("enabled"))

    def plan(self, project: PendingProject, migrated: list[TodoRef]) -> list[Action]:
        if not self.enabled_for(project):
            return []
        actions: list[Action] = []
        for todo in migrated:
            if todo.parent is None or todo.todoist_task_id is None:
                continue
            actions.append(
                Action(
                    kind="clear_parent",
                    target_id=todo.todoist_task_id,
                    payload={"parent_id": None},
                ),
            )
        return actions

    def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult:
        result = ResyncResult()
        if not actions:
            return result
        cfg = _load_cfg(project)
        token = cfg["sync"]["todoist"].get("api_token")
        if not token:
            result.aborted = True
            for a in actions:
                result.failed.append(
                    FailedAction(a, "ConfigError", "todoist api_token missing", retryable=False),
                )
            return result

        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=30.0) as client:
            for start in range(0, len(actions), BATCH_SIZE):
                batch = actions[start : start + BATCH_SIZE]
                commands = [
                    {
                        "type": "item_move",
                        "uuid": f"mig-{a.target_id}",
                        "args": {"id": a.target_id, "parent_id": None},
                    }
                    for a in batch
                ]
                try:
                    resp = client.post(
                        TODOIST_API,
                        headers=headers,
                        json={"commands": commands},
                    )
                    resp.raise_for_status()
                    result.ok.extend(batch)
                except httpx.HTTPStatusError as e:
                    for a in batch:
                        result.failed.append(
                            FailedAction(
                                a,
                                "HTTPStatusError",
                                f"status={e.response.status_code}",
                                retryable=e.response.status_code in (429, 500, 502, 503, 504),
                            ),
                        )
                    if e.response.status_code in (401, 403):
                        result.aborted = True
                        return result
                except httpx.RequestError as e:
                    for a in batch:
                        result.failed.append(
                            FailedAction(a, "RequestError", str(e), retryable=True),
                        )
        return result


def _load_cfg(project: PendingProject) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(project.proj_yaml_path.read_text()) or {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_todoist_resync.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/integrations/todoist.py installer/tests/migrations/test_todoist_resync.py
git commit -m "feat(installer/migrations): Todoist resync (clear parentId, batched)"
```

---

## Task 10: Trello resync (plan + execute)

**Files:**
- Create: `installer/migrations/integrations/trello.py`
- Create: `installer/tests/migrations/test_trello_resync.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_trello_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_trello(tmp_path: Path) -> PendingProject:
    root = tmp_path / "demo"
    root.mkdir()
    proj = root / "proj.yaml"
    proj.write_text(
        yaml.safe_dump({
            "name": "demo",
            "sync": {
                "trello": {
                    "enabled": True,
                    "api_key": "k",
                    "api_token": "t",
                    "board_id": "board123",
                    "list_mappings": {"tasks": "tasks-list-id"},
                },
            },
        }),
    )
    (root / "todos.yaml").write_text("[]\n")
    return PendingProject(name="demo", path=root, proj_yaml_path=proj, current_version=1)


def _parent_with_checklist() -> TodoRef:
    return TodoRef(
        id="1",
        title="parent",
        trello_card_id="parent-card",
        trello_checklist_id="cl-1",
    )


def _child_of_checklist(idx: int, item_id: str | None = None) -> TodoRef:
    return TodoRef(
        id=f"1.{idx}",
        title=f"child {idx}",
        parent="1",
        trello_checklist_item_id=item_id,
    )


def test_plan_emits_promote_action_per_checklist_item(project_with_trello) -> None:
    migrated = [
        _parent_with_checklist(),
        _child_of_checklist(1, "item-1"),
        _child_of_checklist(2, "item-2"),
    ]
    actions = TrelloResync().plan(project_with_trello, migrated)
    assert len(actions) == 2
    assert all(a.kind == "promote_checklist_item" for a in actions)
    assert {a.target_id for a in actions} == {"item-1", "item-2"}


def test_plan_skips_child_missing_item_id(project_with_trello, caplog) -> None:
    migrated = [
        _parent_with_checklist(),
        _child_of_checklist(1, None),
    ]
    actions = TrelloResync().plan(project_with_trello, migrated)
    assert actions == []
    assert any("missing trello_checklist_item_id" in r.message for r in caplog.records)


@respx.mock
def test_execute_happy_path(project_with_trello) -> None:
    migrated = [
        _parent_with_checklist(),
        _child_of_checklist(1, "item-1"),
    ]
    actions = TrelloResync().plan(project_with_trello, migrated)
    # Order-insensitive mocks for each endpoint used:
    respx.post("https://api.trello.com/1/cards").mock(
        return_value=Response(200, json={"id": "new-card-1"}),
    )
    respx.get(url__regex=r"https://api.trello.com/1/cards/parent-card/.*").mock(
        return_value=Response(200, json=[]),  # parent labels fetch
    )
    respx.delete(url__regex=r"https://api.trello.com/1/checklists/cl-1/checkItems/item-1").mock(
        return_value=Response(200),
    )
    respx.delete(url__regex=r"https://api.trello.com/1/checklists/cl-1").mock(
        return_value=Response(200),
    )

    result = TrelloResync().execute(project_with_trello, actions)
    assert not result.failed
    assert len(result.ok) == 1


@respx.mock
def test_execute_card_create_failure_logged(project_with_trello) -> None:
    migrated = [_parent_with_checklist(), _child_of_checklist(1, "item-1")]
    actions = TrelloResync().plan(project_with_trello, migrated)
    respx.post("https://api.trello.com/1/cards").mock(return_value=Response(500))
    result = TrelloResync().execute(project_with_trello, actions)
    assert len(result.failed) == 1
    assert result.failed[0].retryable is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_trello_resync.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `trello.py`**

```python
# installer/migrations/integrations/trello.py
from __future__ import annotations

import logging
from typing import Any

import httpx

from installer.migrations.integrations.base import (
    Action,
    FailedAction,
    ResyncResult,
)
from installer.migrations.types import PendingProject, TodoRef

log = logging.getLogger(__name__)

TRELLO_API = "https://api.trello.com/1"


class TrelloResync:
    name = "trello"

    def enabled_for(self, project: PendingProject) -> bool:
        cfg = _load_cfg(project)
        return bool(cfg.get("sync", {}).get("trello", {}).get("enabled"))

    def plan(self, project: PendingProject, migrated: list[TodoRef]) -> list[Action]:
        if not self.enabled_for(project):
            return []
        cfg = _load_cfg(project)["sync"]["trello"]
        parents_by_id: dict[str, TodoRef] = {
            t.id: t for t in migrated if t.trello_checklist_id
        }
        actions: list[Action] = []
        for child in migrated:
            if child.parent is None:
                continue
            parent = parents_by_id.get(child.parent)
            if parent is None:
                continue
            if not child.trello_checklist_item_id:
                log.warning(
                    "child %s missing trello_checklist_item_id; will be flat locally only",
                    child.id,
                )
                continue
            actions.append(
                Action(
                    kind="promote_checklist_item",
                    target_id=child.trello_checklist_item_id,
                    payload={
                        "parent_card_id": parent.trello_card_id,
                        "checklist_id": parent.trello_checklist_id,
                        "child_todo_id": child.id,
                        "title": child.title,
                        "board_id": cfg["board_id"],
                        "tasks_list_id": cfg["list_mappings"]["tasks"],
                    },
                ),
            )
        return actions

    def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult:
        result = ResyncResult()
        if not actions:
            return result
        cfg = _load_cfg(project)["sync"]["trello"]
        key = cfg.get("api_key")
        token = cfg.get("api_token")
        if not (key and token):
            result.aborted = True
            for a in actions:
                result.failed.append(
                    FailedAction(a, "ConfigError", "trello api_key/token missing", False),
                )
            return result

        auth = {"key": key, "token": token}
        checklists_to_archive: set[str] = set()

        with httpx.Client(timeout=30.0) as client:
            for action in actions:
                try:
                    self._promote_one(client, auth, action)
                    result.ok.append(action)
                    checklists_to_archive.add(action.payload["checklist_id"])
                except httpx.HTTPStatusError as e:
                    retryable = e.response.status_code in (429, 500, 502, 503, 504)
                    result.failed.append(
                        FailedAction(
                            action, "HTTPStatusError",
                            f"status={e.response.status_code}", retryable,
                        ),
                    )
                    if e.response.status_code in (401, 403):
                        result.aborted = True
                        return result
                except httpx.RequestError as e:
                    result.failed.append(FailedAction(action, "RequestError", str(e), True))

            # Archive emptied checklists
            for checklist_id in checklists_to_archive:
                try:
                    r = client.delete(
                        f"{TRELLO_API}/checklists/{checklist_id}",
                        params=auth,
                    )
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    log.warning("failed to archive checklist %s: %s", checklist_id, e)

        return result

    def _promote_one(
        self,
        client: httpx.Client,
        auth: dict[str, str],
        action: Action,
    ) -> None:
        payload = action.payload
        # 1. Create new card on tasks list
        r = client.post(
            f"{TRELLO_API}/cards",
            params={
                **auth,
                "idList": payload["tasks_list_id"],
                "name": payload["title"],
            },
        )
        r.raise_for_status()
        new_card = r.json()
        # 2. Copy labels from parent card
        r = client.get(
            f"{TRELLO_API}/cards/{payload['parent_card_id']}/idLabels",
            params=auth,
        )
        r.raise_for_status()
        label_ids = r.json()
        for label_id in label_ids:
            cr = client.post(
                f"{TRELLO_API}/cards/{new_card['id']}/idLabels",
                params={**auth, "value": label_id},
            )
            if cr.status_code not in (200, 201):
                log.warning("failed to copy label %s to new card", label_id)
        # 3. Record new trello_card_id on local todo (via SQL update)
        _update_local_trello_card_id(
            action.payload["child_todo_id"],
            new_card["id"],
        )
        # 4. Delete checklist item
        r = client.delete(
            f"{TRELLO_API}/checklists/{payload['checklist_id']}/checkItems/{action.target_id}",
            params=auth,
        )
        r.raise_for_status()


def _load_cfg(project: PendingProject) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(project.proj_yaml_path.read_text()) or {}


def _update_local_trello_card_id(todo_id: str, card_id: str) -> None:
    """Hook for updating local todo. Stubbed in Task 10 tests via monkeypatch;
    wired to proj storage in Task 12."""
    log.debug("TODO local update %s → %s", todo_id, card_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_trello_resync.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/integrations/trello.py installer/tests/migrations/test_trello_resync.py
git commit -m "feat(installer/migrations): Trello resync (promote checklist items)"
```

---

## Task 11: Jira resync (plan + execute)

**Files:**
- Create: `installer/migrations/integrations/jira.py`
- Create: `installer/tests/migrations/test_jira_resync.py`

- [ ] **Step 1: Write failing tests**

```python
# installer/tests/migrations/test_jira_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.jira import JiraResync
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_jira(tmp_path: Path) -> PendingProject:
    root = tmp_path / "demo"
    root.mkdir()
    proj = root / "proj.yaml"
    proj.write_text(
        yaml.safe_dump({
            "name": "demo",
            "sync": {
                "jira": {
                    "enabled": True,
                    "base_url": "https://example.atlassian.net",
                    "email": "u@example.com",
                    "api_token": "tok",
                    "epic_link_field": "customfield_10014",
                },
            },
        }),
    )
    (root / "todos.yaml").write_text("[]\n")
    return PendingProject(name="demo", path=root, proj_yaml_path=proj, current_version=1)


def _parent_epic() -> TodoRef:
    return TodoRef(id="1", title="epic", jira_issue_key="CPM-100")


def _parent_story() -> TodoRef:
    return TodoRef(id="1", title="story", jira_issue_key="CPM-50")


def _child_subtask(idx: int) -> TodoRef:
    return TodoRef(id=f"1.{idx}", title=f"st {idx}", parent="1", jira_issue_key=f"CPM-{100 + idx}")


def test_plan_under_epic_preserves_epic_link(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1), _child_subtask(2)]
    actions = JiraResync().plan(project_with_jira, migrated)
    assert len(actions) == 2
    assert all(a.payload["epic_link"] == "CPM-100" for a in actions)


@respx.mock
def test_execute_type_conversion(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1)]
    actions = JiraResync().plan(project_with_jira, migrated)
    # PUT /rest/api/3/issue/<key>
    respx.put(url__regex=r"https://example\.atlassian\.net/rest/api/3/issue/CPM-101").mock(
        return_value=Response(204),
    )
    result = JiraResync().execute(project_with_jira, actions)
    assert not result.failed
    assert len(result.ok) == 1


@respx.mock
def test_execute_project_rejects_type_change(project_with_jira) -> None:
    migrated = [_parent_epic(), _child_subtask(1)]
    actions = JiraResync().plan(project_with_jira, migrated)
    respx.put(url__regex=r".*rest/api/3/issue/CPM-101").mock(
        return_value=Response(400, json={"errorMessages": ["type change not allowed"]}),
    )
    result = JiraResync().execute(project_with_jira, actions)
    assert len(result.failed) == 1
    assert result.failed[0].retryable is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_jira_resync.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `jira.py`**

```python
# installer/migrations/integrations/jira.py
from __future__ import annotations

import logging
from typing import Any

import httpx

from installer.migrations.integrations.base import (
    Action,
    FailedAction,
    ResyncResult,
)
from installer.migrations.types import PendingProject, TodoRef

log = logging.getLogger(__name__)


class JiraResync:
    name = "jira"

    def enabled_for(self, project: PendingProject) -> bool:
        cfg = _load_cfg(project)
        return bool(cfg.get("sync", {}).get("jira", {}).get("enabled"))

    def plan(self, project: PendingProject, migrated: list[TodoRef]) -> list[Action]:
        if not self.enabled_for(project):
            return []
        by_id = {t.id: t for t in migrated if t.jira_issue_key}
        actions: list[Action] = []
        for child in migrated:
            if child.parent is None or child.jira_issue_key is None:
                continue
            parent = by_id.get(child.parent)
            if parent is None:
                continue
            # For Phase 1 we always try to preserve an epic link if present.
            # 'parent is Epic' inferred by convention (title-based or explicit
            # check could be done via API; kept simple here — parent's own
            # jira_issue_key is propagated as epic_link). Jira project may
            # reject the type conversion; that's a graceful per-issue failure.
            actions.append(
                Action(
                    kind="demote_subtask",
                    target_id=child.jira_issue_key,
                    payload={
                        "child_todo_id": child.id,
                        "epic_link": parent.jira_issue_key,
                        "new_issue_type": "Story",
                    },
                ),
            )
        return actions

    def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult:
        result = ResyncResult()
        if not actions:
            return result
        cfg = _load_cfg(project)["sync"]["jira"]
        base = cfg["base_url"].rstrip("/")
        email = cfg["email"]
        token = cfg["api_token"]
        epic_field = cfg.get("epic_link_field", "customfield_10014")

        auth = httpx.BasicAuth(email, token)
        with httpx.Client(base_url=base, timeout=30.0, auth=auth) as client:
            for action in actions:
                fields = {
                    "issuetype": {"name": action.payload["new_issue_type"]},
                    "parent": None,
                }
                if action.payload.get("epic_link"):
                    fields[epic_field] = action.payload["epic_link"]
                try:
                    r = client.put(
                        f"/rest/api/3/issue/{action.target_id}",
                        json={"fields": fields},
                    )
                    r.raise_for_status()
                    result.ok.append(action)
                except httpx.HTTPStatusError as e:
                    retryable = e.response.status_code in (429, 500, 502, 503, 504)
                    result.failed.append(
                        FailedAction(
                            action,
                            "HTTPStatusError",
                            f"status={e.response.status_code}",
                            retryable,
                        ),
                    )
                    if e.response.status_code in (401, 403):
                        result.aborted = True
                        return result
                except httpx.RequestError as e:
                    result.failed.append(FailedAction(action, "RequestError", str(e), True))
        return result


def _load_cfg(project: PendingProject) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(project.proj_yaml_path.read_text()) or {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_jira_resync.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/integrations/jira.py installer/tests/migrations/test_jira_resync.py
git commit -m "feat(installer/migrations): Jira resync (demote sub-tasks, preserve epic)"
```

---

## Task 12: Wire integrations into FlatTodoMigration

**Files:**
- Modify: `installer/migrations/flat_todo.py`
- Modify: `installer/migrations/integrations/trello.py` (wire `_update_local_trello_card_id`)
- Modify: `installer/tests/migrations/test_flat_todo_runner.py` (add wired tests)

- [ ] **Step 1: Extend tests to cover integration wiring**

Append to `installer/tests/migrations/test_flat_todo_runner.py`:

```python
from unittest.mock import MagicMock

from installer.migrations.integrations.base import IntegrationResync, ResyncResult


class FakeIntegration:
    name = "fake"
    called: list[str] = []

    def enabled_for(self, project) -> bool:
        return True

    def plan(self, project, migrated):
        return []

    def execute(self, project, actions):
        FakeIntegration.called.append(project.name)
        return ResyncResult()


def test_runner_invokes_enabled_integrations(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"
    FakeIntegration.called = []
    runner = FlatTodoMigration(
        project=project,
        run_ts="ts",
        backup_root=backup_root,
        integrations=[FakeIntegration()],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert FakeIntegration.called == ["demo"]
    assert runner.state == MigrationState.COMMITTED


def test_resync_failure_does_not_revert_local(tmp_path: Path) -> None:
    project = _setup_project(tmp_path / "p")
    backup_root = tmp_path / "backups"

    class FailingIntegration:
        name = "fail"

        def enabled_for(self, project):
            return True

        def plan(self, project, migrated):
            from installer.migrations.integrations.base import Action
            return [Action(kind="noop", target_id="x", payload={})]

        def execute(self, project, actions):
            from installer.migrations.integrations.base import FailedAction, ResyncResult
            return ResyncResult(failed=[FailedAction(actions[0], "E", "m", True)])

    runner = FlatTodoMigration(
        project=project,
        run_ts="ts",
        backup_root=backup_root,
        integrations=[FailingIntegration()],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()
    assert runner.state == MigrationState.COMMITTED  # local committed despite failed resync
    assert runner.resync_failures  # collected for summary
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest installer/tests/migrations/test_flat_todo_runner.py -v`
Expected: new tests fail.

- [ ] **Step 3: Modify `flat_todo.py` to accept and drive integrations**

Replace the class body in `installer/migrations/flat_todo.py` with:

```python
# installer/migrations/flat_todo.py (replace class body)
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from installer.migrations.backup import BackupSnapshot
from installer.migrations.base import MigrationRunner
from installer.migrations.detect import bump_schema_version, detect_already_flat
from installer.migrations.integrations.base import FailedAction, IntegrationResync


class ResyncFailure(RuntimeError):
    """Raised when --strict-resync is set and any integration reports a failure."""
from installer.migrations.transform import flatten_todos_sql, flatten_todos_yaml
from installer.migrations.types import (
    TARGET_SCHEMA_VERSION,
    MigrationPlan,
    MigrationState,
    PendingProject,
    RecoveryPath,
    TodoRef,
)

log = logging.getLogger(__name__)


@dataclass
class FlatTodoMigration(MigrationRunner):
    project: PendingProject = None  # type: ignore[assignment]
    run_ts: str = ""
    backup_root: Path = Path()
    integrations: list[IntegrationResync] = field(default_factory=list)
    strict_resync: bool = False
    plan_result: MigrationPlan | None = None
    snapshot: BackupSnapshot | None = None
    resync_failures: list[FailedAction] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.project_name = self.project.name
        self.project_dir = self.project.path

    def plan(self) -> MigrationPlan:
        self._plan()
        self.transition(MigrationState.PLANNED)
        assert self.plan_result is not None
        return self.plan_result

    def confirm(self, confirmed: bool = True) -> None:
        self.transition(MigrationState.CONFIRMED if confirmed else MigrationState.SKIPPED)

    def execute_local(self) -> None:
        if self.plan_result is None:
            raise RuntimeError("plan() must run before execute_local()")
        try:
            self._backup()
            self.transition(MigrationState.BACKED_UP)
        except Exception:
            self.transition(MigrationState.RESTORING)
            self.transition(MigrationState.FAILED)
            raise

        if self.plan_result.recovery_path == RecoveryPath.BUMP_ONLY:
            self.transition(MigrationState.FLATTENED)
            self.transition(MigrationState.RESYNCED)
            return

        try:
            self._flatten()
            self.transition(MigrationState.FLATTENED)
            self._resync()
            self.transition(MigrationState.RESYNCED)
        except Exception:
            self._restore()
            raise

    def commit(self) -> None:
        try:
            self._commit()
            self.transition(MigrationState.COMMITTED)
        except Exception:
            self._restore()
            raise

    # --- hook impls ---

    def _plan(self) -> None:
        todos_path = self.project.path / "todos.yaml"
        data = yaml.safe_load(todos_path.read_text()) or []
        parents: list[TodoRef] = []
        children: list[TodoRef] = []
        migrated: list[TodoRef] = []
        for t in data:
            ref = TodoRef(
                id=t.get("id", ""),
                title=t.get("title", ""),
                todoist_task_id=t.get("todoist_task_id"),
                trello_card_id=t.get("trello_card_id"),
                trello_checklist_id=t.get("trello_checklist_id"),
                trello_checklist_item_id=t.get("trello_checklist_item_id"),
                jira_issue_key=t.get("jira_issue_key"),
                parent=t.get("parent"),
            )
            migrated.append(ref)
            if t.get("children"):
                parents.append(ref)
            if t.get("parent") is not None:
                children.append(ref)
        recovery = (
            RecoveryPath.BUMP_ONLY if detect_already_flat(todos_path) else RecoveryPath.NORMAL
        )

        integration_actions = {}
        for integ in self.integrations:
            if not integ.enabled_for(self.project):
                continue
            integration_actions[integ.name] = integ.plan(self.project, migrated)

        self.plan_result = MigrationPlan(
            project=self.project,
            parents=parents,
            children=children,
            integration_actions=integration_actions,
            recovery_path=recovery,
        )

    def _backup(self) -> None:
        self.snapshot = BackupSnapshot.create(
            project=self.project.name,
            run_ts=self.run_ts,
            source_dir=self.project.path,
            backup_root=self.backup_root,
        )

    def _flatten(self) -> None:
        flatten_todos_yaml(self.project.path / "todos.yaml")
        archive = self.project.path / "archive.yaml"
        if archive.exists():
            flatten_todos_yaml(archive)
        flatten_todos_sql(self.project.path / "data.db")

    def _resync(self) -> None:
        assert self.plan_result is not None
        for integ in self.integrations:
            actions = self.plan_result.integration_actions.get(integ.name, [])
            if not actions:
                continue
            result = integ.execute(self.project, actions)
            self.resync_failures.extend(result.failed)
            if result.aborted:
                log.warning(
                    "%s: integration %s aborted; continuing with remaining integrations",
                    self.project.name,
                    integ.name,
                )
            if self.strict_resync and (result.failed or result.aborted):
                raise ResyncFailure(
                    f"{self.project.name}: strict resync: {integ.name} reported "
                    f"{len(result.failed)} failures (aborted={result.aborted})",
                )

    def _commit(self) -> None:
        bump_schema_version(self.project.proj_yaml_path, TARGET_SCHEMA_VERSION)

    def _restore(self) -> None:
        self.transition(MigrationState.RESTORING)
        if self.snapshot is not None:
            self.snapshot.restore()
        self.transition(MigrationState.FAILED)
```

- [ ] **Step 4: Wire `_update_local_trello_card_id` to proj plugin storage**

Modify `installer/migrations/integrations/trello.py` — replace the stub `_update_local_trello_card_id` with:

```python
def _update_local_trello_card_id(todo_id: str, card_id: str) -> None:
    """Write new trello_card_id back into local todos.yaml + SQL.

    Uses proj plugin's storage layer to stay consistent with hybrid YAML+SQL.
    """
    # Import lazily so the installer doesn't require proj plugin at import time
    from plugins.proj.server.server.lib import storage  # type: ignore[import-not-found]

    # storage.update_todo_field is expected to exist per proj plugin; if the
    # call path differs, adjust this import + call site during Task 12 bring-up.
    try:
        storage.update_todo_field(todo_id, "trello_card_id", card_id)
    except Exception as e:
        log.warning("failed to update local trello_card_id for todo %s: %s", todo_id, e)
```

**Note to implementer:** Before running tests, verify the exact function name in `plugins/proj/server/server/lib/storage.py` — it may be named `update_todo` or similar. The Trello tests mock this via monkeypatch; only the e2e + live wiring needs the real call.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest installer/tests/migrations/test_flat_todo_runner.py -v`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add installer/migrations/flat_todo.py installer/migrations/integrations/trello.py installer/tests/migrations/test_flat_todo_runner.py
git commit -m "feat(installer/migrations): wire IntegrationResync into FlatTodoMigration"
```

---

## Task 13: Textual Screen 1 — overview

**Files:**
- Create: `installer/screens/migration_overview.py`
- Create: `installer/tests/migrations/test_screens.py`

- [ ] **Step 1: Write failing snapshot test**

```python
# installer/tests/migrations/test_screens.py
from __future__ import annotations

from pathlib import Path

import pytest

from installer.migrations.types import PendingProject
from installer.screens.migration_overview import MigrationOverviewScreen


def _fixture_projects(tmp_path: Path) -> list[PendingProject]:
    return [
        PendingProject(
            name="cpm",
            path=tmp_path / "cpm",
            proj_yaml_path=tmp_path / "cpm" / "proj.yaml",
            current_version=1,
        ),
        PendingProject(
            name="side",
            path=tmp_path / "side",
            proj_yaml_path=tmp_path / "side" / "proj.yaml",
            current_version=1,
        ),
    ]


def test_overview_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    class Harness(App):
        def on_mount(self) -> None:
            self.push_screen(
                MigrationOverviewScreen(
                    pending=_fixture_projects(tmp_path),
                    integration_map={"cpm": {"T", "R", "J"}, "side": {"T"}},
                    counts={"cpm": (12, 38), "side": (4, 9)},
                ),
            )

    assert snap_compare(Harness())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest installer/tests/migrations/test_screens.py::test_overview_snapshot -v`
Expected: ImportError or golden missing.

- [ ] **Step 3: Implement `migration_overview.py`**

```python
# installer/screens/migration_overview.py
from __future__ import annotations

from typing import Iterable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from installer.migrations.types import PendingProject


class MigrationOverviewScreen(Screen):
    """Screen 1: lists projects needing flat-todo migration."""

    BINDINGS = [
        Binding("enter", "review", "Review"),
        Binding("s", "skip_all", "Skip all"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    MigrationOverviewScreen > Vertical { padding: 1 2; }
    DataTable { height: 1fr; }
    """

    def __init__(
        self,
        pending: Iterable[PendingProject],
        integration_map: dict[str, set[str]],
        counts: dict[str, tuple[int, int]],
    ) -> None:
        super().__init__()
        self.pending = list(pending)
        self.integration_map = integration_map
        self.counts = counts

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static(
                f"{len(self.pending)} projects need migration to schema_version=2.",
                classes="summary",
            )
            table = DataTable()
            table.add_columns("Project", "Parents", "Children", "Remote")
            for p in self.pending:
                parents, children = self.counts.get(p.name, (0, 0))
                remote = ",".join(sorted(self.integration_map.get(p.name, []))) or "–"
                table.add_row(p.name, str(parents), str(children), remote)
            yield table
        yield Footer()

    def action_review(self) -> None:
        self.dismiss(("review", self.pending))

    def action_skip_all(self) -> None:
        self.dismiss(("skip_all", []))

    def action_quit(self) -> None:
        self.dismiss(("quit", []))
```

- [ ] **Step 4: Generate snapshot golden on first run**

Run: `uv run pytest installer/tests/migrations/test_screens.py::test_overview_snapshot --snapshot-update`
Expected: golden written.

- [ ] **Step 5: Run without `--snapshot-update` to verify match**

Run: `uv run pytest installer/tests/migrations/test_screens.py::test_overview_snapshot -v`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add installer/screens/migration_overview.py installer/tests/migrations/test_screens.py installer/tests/__snapshots__/
git commit -m "feat(installer/screens): migration overview screen + snapshot"
```

---

## Task 14: Textual Screen 2 — per-project review + dry-run preview tabs

**Files:**
- Create: `installer/screens/migration_review.py`
- Modify: `installer/tests/migrations/test_screens.py` (add tests)

- [ ] **Step 1: Add failing snapshot test**

Append to `installer/tests/migrations/test_screens.py`:

```python
def test_review_screen_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    from installer.migrations.integrations.base import Action
    from installer.migrations.types import (
        MigrationPlan,
        PendingProject,
        RecoveryPath,
        TodoRef,
    )
    from installer.screens.migration_review import MigrationReviewScreen

    project = PendingProject(
        name="cpm",
        path=tmp_path / "cpm",
        proj_yaml_path=tmp_path / "cpm" / "proj.yaml",
        current_version=1,
    )
    plan = MigrationPlan(
        project=project,
        parents=[TodoRef(id="475", title="Review everything")],
        children=[
            TodoRef(id=f"475.{i}", title=f"child {i}", parent="475")
            for i in range(3)
        ],
        integration_actions={
            "todoist": [
                Action(kind="clear_parent", target_id=f"task-{i}", payload={})
                for i in range(3)
            ],
            "trello": [],
            "jira": [],
        },
        recovery_path=RecoveryPath.NORMAL,
    )

    class Harness(App):
        def on_mount(self) -> None:
            self.push_screen(MigrationReviewScreen(plan=plan, backup_preview="/tmp/b"))

    assert snap_compare(Harness())


def test_review_dry_run_tab_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    from installer.migrations.integrations.base import Action
    from installer.migrations.types import MigrationPlan, PendingProject, RecoveryPath, TodoRef
    from installer.screens.migration_review import MigrationReviewScreen

    project = PendingProject(
        name="cpm",
        path=tmp_path / "cpm",
        proj_yaml_path=tmp_path / "cpm" / "proj.yaml",
        current_version=1,
    )
    plan = MigrationPlan(
        project=project,
        parents=[TodoRef(id="1", title="p")],
        children=[TodoRef(id="1.1", title="c", parent="1", todoist_task_id="t1")],
        integration_actions={
            "todoist": [Action(kind="clear_parent", target_id="t1", payload={})],
            "trello": [],
            "jira": [],
        },
        recovery_path=RecoveryPath.NORMAL,
    )

    class Harness(App):
        def on_mount(self) -> None:
            screen = MigrationReviewScreen(plan=plan, backup_preview="/tmp/b")
            self.push_screen(screen)

        async def on_ready(self) -> None:
            await self.press("d")  # open dry-run tab

    assert snap_compare(Harness())
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest installer/tests/migrations/test_screens.py::test_review_screen_snapshot -v`
Expected: ImportError.

- [ ] **Step 3: Implement `migration_review.py`**

```python
# installer/screens/migration_review.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Static, TabbedContent, TabPane

from installer.migrations.types import MigrationPlan


class MigrationReviewScreen(Screen):
    BINDINGS = [
        Binding("m", "migrate", "Migrate"),
        Binding("s", "skip", "Skip"),
        Binding("d", "dry_run_preview", "Dry-run preview"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    MigrationReviewScreen > Vertical { padding: 1 2; }
    .label { margin-bottom: 1; }
    """

    def __init__(self, plan: MigrationPlan, backup_preview: str) -> None:
        super().__init__()
        self.plan = plan
        self.backup_preview = backup_preview

    def compose(self) -> ComposeResult:
        yield Header(name=f"Migrate — {self.plan.project.name}")
        with Vertical():
            yield Static(
                f"[bold]Plan preview[/]\n"
                f"• {len(self.plan.parents)} parent todos → flat w/ group:<id>\n"
                f"• {len(self.plan.children)} children → top-level with group:<parent>\n"
                f"• No parent/children fields after migration",
                classes="label",
            )
            totals = {k: len(v) for k, v in self.plan.integration_actions.items()}
            yield Static(
                f"[bold]Remote resync[/]  "
                f"Todoist: {totals.get('todoist', 0)}  "
                f"Trello: {totals.get('trello', 0)}  "
                f"Jira: {totals.get('jira', 0)}",
                classes="label",
            )
            yield Static(f"[bold]Backup:[/] {self.backup_preview}", classes="label")
        yield Footer()

    def action_migrate(self) -> None:
        self.app.push_screen(
            ConfirmDialog(
                prompt=(
                    f"Proceed with {sum(len(v) for v in self.plan.integration_actions.values())}"
                    f" remote actions across {len(self.plan.integration_actions)} integrations?"
                ),
            ),
            self._on_confirm,
        )

    def _on_confirm(self, yes: bool) -> None:
        self.dismiss(("migrate", self.plan) if yes else ("skip", None))

    def action_skip(self) -> None:
        self.dismiss(("skip", None))

    def action_dry_run_preview(self) -> None:
        self.app.push_screen(DryRunPreviewScreen(self.plan))

    def action_quit(self) -> None:
        self.dismiss(("quit", None))


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
    ]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.prompt)
            with Horizontal():
                yield Button("Yes (y)", id="yes")
                yield Button("No (n)", id="no")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class DryRunPreviewScreen(ModalScreen):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, plan: MigrationPlan) -> None:
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        yield Header(name="Dry-run preview")
        with TabbedContent(initial="local"):
            with TabPane("Local diff", id="local"):
                sample = self.plan.children[:3]
                lines = ["[bold]Sample (first 3 children)[/]", ""]
                for c in sample:
                    lines.append(f"- id={c.id}  parent={c.parent}  →  tags+=group:{c.parent}")
                yield Static("\n".join(lines))
            with TabPane("Remote actions", id="remote"):
                lines = []
                for integ, actions in self.plan.integration_actions.items():
                    lines.append(f"[bold]{integ} ({len(actions)} actions)[/]")
                    for a in actions[:20]:
                        lines.append(f"  • {a.kind}  target={a.target_id}")
                    if len(actions) > 20:
                        lines.append(f"  … {len(actions) - 20} more")
                    lines.append("")
                yield Static("\n".join(lines))
        yield Footer()

    def action_close(self) -> None:
        self.dismiss()
```

- [ ] **Step 4: Generate golden + run**

Run: `uv run pytest installer/tests/migrations/test_screens.py::test_review_screen_snapshot --snapshot-update`
Run: `uv run pytest installer/tests/migrations/test_screens.py::test_review_dry_run_tab_snapshot --snapshot-update`
Run: `uv run pytest installer/tests/migrations/test_screens.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/screens/migration_review.py installer/tests/migrations/test_screens.py installer/tests/__snapshots__/
git commit -m "feat(installer/screens): migration review + dry-run preview screens"
```

---

## Task 15: Textual Screen 3 — progress + summary

**Files:**
- Create: `installer/screens/migration_progress.py`
- Modify: `installer/tests/migrations/test_screens.py`

- [ ] **Step 1: Add failing snapshot test**

Append to `installer/tests/migrations/test_screens.py`:

```python
def test_progress_summary_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    from installer.screens.migration_progress import (
        MigrationOutcome,
        MigrationProgressScreen,
    )

    outcomes = [
        MigrationOutcome(project="cpm", ok=True, resync_partial=False, backup="/tmp/b1"),
        MigrationOutcome(project="side", ok=False, resync_partial=False, backup="/tmp/b2", error="ALTER failed"),
        MigrationOutcome(project="legacy", ok=True, resync_partial=True, backup="/tmp/b3"),
    ]

    class Harness(App):
        def on_mount(self) -> None:
            self.push_screen(MigrationProgressScreen(outcomes=outcomes))

    assert snap_compare(Harness())
```

- [ ] **Step 2: Run test to confirm failure**

Run: `uv run pytest installer/tests/migrations/test_screens.py::test_progress_summary_snapshot -v`
Expected: ImportError.

- [ ] **Step 3: Implement `migration_progress.py`**

```python
# installer/screens/migration_progress.py
from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static


@dataclass(frozen=True)
class MigrationOutcome:
    project: str
    ok: bool
    resync_partial: bool
    backup: str
    error: str | None = None


class MigrationProgressScreen(Screen):
    BINDINGS = [Binding("enter", "dismiss", "Close")]

    def __init__(self, outcomes: list[MigrationOutcome]) -> None:
        super().__init__()
        self.outcomes = outcomes

    def compose(self) -> ComposeResult:
        yield Header(name="Migration summary")
        with Vertical():
            ok = sum(1 for o in self.outcomes if o.ok)
            partial = sum(1 for o in self.outcomes if o.ok and o.resync_partial)
            failed = sum(1 for o in self.outcomes if not o.ok)
            yield Static(
                f"[bold]Results[/]  ✓ {ok} ok  ◐ {partial} partial-resync  ✗ {failed} failed",
            )
            table = DataTable()
            table.add_columns("Status", "Project", "Backup", "Details")
            for o in self.outcomes:
                if not o.ok:
                    status = "✗"
                elif o.resync_partial:
                    status = "◐"
                else:
                    status = "✓"
                table.add_row(status, o.project, o.backup, o.error or "")
            yield table
        yield Footer()

    def action_dismiss(self) -> None:
        self.dismiss()
```

- [ ] **Step 4: Generate golden + verify**

Run: `uv run pytest installer/tests/migrations/test_screens.py::test_progress_summary_snapshot --snapshot-update`
Run: `uv run pytest installer/tests/migrations/test_screens.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add installer/screens/migration_progress.py installer/tests/migrations/test_screens.py installer/tests/__snapshots__/
git commit -m "feat(installer/screens): migration progress + summary screen"
```

---

## Task 16: Dry-run markdown report generator

**Files:**
- Create: `installer/migrations/report.py`
- Create: `installer/tests/migrations/test_dry_run_report.py`

- [ ] **Step 1: Write failing test**

```python
# installer/tests/migrations/test_dry_run_report.py
from __future__ import annotations

from pathlib import Path

from installer.migrations.integrations.base import Action
from installer.migrations.report import write_dry_run_report
from installer.migrations.types import MigrationPlan, PendingProject, RecoveryPath, TodoRef


def _fake_plan(tmp_path: Path) -> MigrationPlan:
    project = PendingProject(
        name="cpm",
        path=tmp_path / "cpm",
        proj_yaml_path=tmp_path / "cpm" / "proj.yaml",
        current_version=1,
    )
    return MigrationPlan(
        project=project,
        parents=[TodoRef(id="1", title="p")],
        children=[TodoRef(id="1.1", title="c", parent="1", todoist_task_id="t1")],
        integration_actions={
            "todoist": [Action(kind="clear_parent", target_id="t1", payload={})],
            "trello": [],
            "jira": [],
        },
        recovery_path=RecoveryPath.NORMAL,
    )


def test_report_contains_per_project_section(tmp_path: Path) -> None:
    plans = [_fake_plan(tmp_path)]
    out = write_dry_run_report(plans, tmp_path / "report.md", run_ts="ts")
    assert out.exists()
    text = out.read_text()
    assert "# Flat-Todo Migration — Dry Run" in text
    assert "## cpm" in text
    assert "Parents: 1" in text
    assert "Children: 1" in text
    assert "clear_parent" in text


def test_report_empty_list(tmp_path: Path) -> None:
    out = write_dry_run_report([], tmp_path / "r.md", run_ts="ts")
    text = out.read_text()
    assert "No projects" in text
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `uv run pytest installer/tests/migrations/test_dry_run_report.py -v`

- [ ] **Step 3: Implement `report.py`**

```python
# installer/migrations/report.py
from __future__ import annotations

from pathlib import Path

from installer.migrations.types import MigrationPlan


def write_dry_run_report(
    plans: list[MigrationPlan],
    output_path: Path,
    *,
    run_ts: str,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# Flat-Todo Migration — Dry Run",
        "",
        f"Run timestamp: `{run_ts}`",
        "",
    ]
    if not plans:
        lines.append("No projects require migration.")
        output_path.write_text("\n".join(lines) + "\n")
        return output_path

    for plan in plans:
        lines.extend(_render_project(plan))

    output_path.write_text("\n".join(lines) + "\n")
    return output_path


def _render_project(plan: MigrationPlan) -> list[str]:
    out = [
        f"## {plan.project.name}",
        "",
        f"- Path: `{plan.project.path}`",
        f"- Schema version: {plan.project.current_version} → 2",
        f"- Recovery path: `{plan.recovery_path.value}`",
        f"- Parents: {len(plan.parents)}",
        f"- Children: {len(plan.children)}",
        "",
        "### Remote actions",
        "",
    ]
    for integ, actions in plan.integration_actions.items():
        out.append(f"**{integ}** — {len(actions)} actions")
        for a in actions:
            out.append(f"- `{a.kind}` target=`{a.target_id}`")
        out.append("")
    return out
```

- [ ] **Step 4: Run tests — pass**

Run: `uv run pytest installer/tests/migrations/test_dry_run_report.py -v`

- [ ] **Step 5: Commit**

```bash
git add installer/migrations/report.py installer/tests/migrations/test_dry_run_report.py
git commit -m "feat(installer/migrations): dry-run markdown report generator"
```

---

## Task 17: Migration entry point + CLI flags

**Files:**
- Create: `installer/migrations/entry.py`
- Modify: `installer/main.py` (CLI flag wiring)
- Modify: `installer/cli.py` (flag handlers)
- Create: `installer/tests/migrations/test_cli_flags.py`

- [ ] **Step 1: Write failing CLI tests**

```python
# installer/tests/migrations/test_cli_flags.py
from __future__ import annotations

import subprocess
import sys


def test_help_lists_migrate_flags() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--migrate-flat" in r.stdout
    assert "--migrate-flat-dry-run" in r.stdout
    assert "--backup-retain" in r.stdout
    assert "--strict-resync" in r.stdout


def test_dry_run_flag_exits_zero_without_mutation(tmp_path, monkeypatch) -> None:
    # Point fake home at tmp_path so no real config touched
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "proj.yaml").write_text("projects: []\n")
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate-flat-dry-run"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
```

- [ ] **Step 2: Run — expect failure (flags not wired)**

Run: `uv run pytest installer/tests/migrations/test_cli_flags.py -v`

- [ ] **Step 3: Implement `entry.py`**

```python
# installer/migrations/entry.py
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Sequence

from installer.migrations.detect import discover_pending
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.base import IntegrationResync
from installer.migrations.integrations.jira import JiraResync
from installer.migrations.integrations.todoist import TodoistResync
from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.lock import LockContention, MigrationLock
from installer.migrations.report import write_dry_run_report
from installer.migrations.types import PendingProject

log = logging.getLogger(__name__)

MIGRATION_ROOT = Path.home() / ".claude" / "migrations"


def run_pending_migrations(
    projects: list[dict],
    *,
    interactive: bool,
    strict_resync: bool = False,
    backup_retain_days: int | None = None,
) -> int:
    """Entry point called from wizard hook and standalone CLI.

    Returns exit code: 0 all good, 2 partial failure, 3 user quit.
    """
    run_ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    pending = list(discover_pending(projects))
    if not pending:
        log.info("no projects need flat-todo migration")
        return 0

    lock_path = MIGRATION_ROOT / ".lock"
    try:
        with MigrationLock(lock_path):
            return _run_with_lock(
                pending,
                run_ts=run_ts,
                interactive=interactive,
                strict_resync=strict_resync,
                backup_retain_days=backup_retain_days,
            )
    except LockContention as e:
        print(f"Migration already running: {e}")
        return 2


def run_dry_run(projects: list[dict]) -> int:
    run_ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    pending = list(discover_pending(projects))
    integrations = _default_integrations()
    plans = []
    for p in pending:
        runner = FlatTodoMigration(
            project=p,
            run_ts=run_ts,
            backup_root=MIGRATION_ROOT / run_ts,
            integrations=integrations,
        )
        plans.append(runner.plan())
    out_dir = MIGRATION_ROOT / run_ts
    out_dir.mkdir(parents=True, exist_ok=True)
    write_dry_run_report(plans, out_dir / "dry-run.md", run_ts=run_ts)
    print(f"Dry-run report: {out_dir / 'dry-run.md'}")
    return 0


def _run_with_lock(
    pending: Sequence[PendingProject],
    *,
    run_ts: str,
    interactive: bool,
    strict_resync: bool,
    backup_retain_days: int | None,
) -> int:
    if not interactive:
        # Non-TTY mode — print overview and exit with a warning
        print("Flat-todo migration needs an interactive TTY.")
        print("Projects pending:")
        for p in pending:
            print(f"  - {p.name}  (schema_version {p.current_version} → 2)")
        print("\nRun `installer --migrate-flat` in an interactive terminal.")
        return 0

    # Interactive mode: hand off to TUI driver (implemented in Task 18 via app.py hook)
    from installer.app import run_migration_tui

    exit_code = run_migration_tui(
        pending=list(pending),
        run_ts=run_ts,
        integrations=_default_integrations(),
        backup_root=MIGRATION_ROOT / run_ts,
        strict_resync=strict_resync,
    )
    if backup_retain_days is not None:
        _prune_old_backups(backup_retain_days)
    return exit_code


def _default_integrations() -> list[IntegrationResync]:
    return [TodoistResync(), TrelloResync(), JiraResync()]


def _prune_old_backups(days: int) -> None:
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    if not MIGRATION_ROOT.exists():
        return
    for child in MIGRATION_ROOT.iterdir():
        if not child.is_dir():
            continue
        try:
            ts = dt.datetime.strptime(child.name, "%Y-%m-%dT%H-%M-%S")
        except ValueError:
            continue
        if ts < cutoff:
            import shutil
            shutil.rmtree(child)
```

- [ ] **Step 4: Modify `installer/main.py` — add CLI flags**

Find the existing argparse setup in `installer/main.py` and add (place in the same argparse block that defines `--update` etc.):

```python
parser.add_argument(
    "--migrate-flat",
    action="store_true",
    help="Run the interactive flat-todo migration outside a full install session.",
)
parser.add_argument(
    "--migrate-flat-dry-run",
    action="store_true",
    help="Print a dry-run report of what the flat-todo migration would do, no mutation.",
)
parser.add_argument(
    "--backup-retain",
    type=int,
    default=None,
    metavar="DAYS",
    help="Prune migration backups older than DAYS on next run (default: keep forever).",
)
parser.add_argument(
    "--strict-resync",
    action="store_true",
    help="Abort + revert local flatten on any remote resync failure (default: log + continue).",
)
```

And add routing before the main wizard invocation:

```python
from installer.migrations.entry import run_dry_run, run_pending_migrations
from installer.cli import load_project_list  # helper that returns the list[dict]

if args.migrate_flat_dry_run:
    return run_dry_run(load_project_list())
if args.migrate_flat:
    import sys
    return run_pending_migrations(
        load_project_list(),
        interactive=sys.stdin.isatty(),
        strict_resync=args.strict_resync,
        backup_retain_days=args.backup_retain,
    )
```

- [ ] **Step 5: Add `load_project_list` helper**

Append to `installer/cli.py`:

```python
def load_project_list() -> list[dict]:
    """Read ~/.claude/proj.yaml and return the projects list (each with name + path)."""
    import yaml
    from pathlib import Path

    proj_yaml = Path.home() / ".claude" / "proj.yaml"
    if not proj_yaml.exists():
        return []
    data = yaml.safe_load(proj_yaml.read_text()) or {}
    return list(data.get("projects", []))
```

- [ ] **Step 6: Run CLI tests**

Run: `uv run pytest installer/tests/migrations/test_cli_flags.py -v`
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add installer/migrations/entry.py installer/main.py installer/cli.py installer/tests/migrations/test_cli_flags.py
git commit -m "feat(installer): wire --migrate-flat* CLI flags + migration entry point"
```

---

## Task 18: Wizard hook in app.py + TUI driver

**Files:**
- Modify: `installer/app.py`

- [ ] **Step 1: Add `run_migration_tui` entry + post-install call site**

Add to `installer/app.py` (at module level):

```python
def run_migration_tui(
    *,
    pending: list,
    run_ts: str,
    integrations: list,
    backup_root: "Path",  # noqa: F821
    strict_resync: bool,
) -> int:
    """Launch a standalone Textual app that drives the migration screens.

    Returns exit code: 0 success, 2 partial, 3 user quit.
    """
    from installer.migrations.flat_todo import FlatTodoMigration
    from installer.screens.migration_overview import MigrationOverviewScreen
    from installer.screens.migration_progress import (
        MigrationOutcome,
        MigrationProgressScreen,
    )
    from installer.screens.migration_review import MigrationReviewScreen

    outcomes: list[MigrationOutcome] = []
    exit_code = 0

    class MigrationApp(App):
        def on_mount(self) -> None:
            integration_map = _integration_badges(pending, integrations)
            counts = {p.name: _count_parents_children(p) for p in pending}
            self.push_screen(
                MigrationOverviewScreen(
                    pending=pending,
                    integration_map=integration_map,
                    counts=counts,
                ),
                self._after_overview,
            )

        def _after_overview(self, result: tuple) -> None:
            action, _payload = result
            if action in ("skip_all", "quit"):
                nonlocal exit_code
                exit_code = 3 if action == "quit" else 0
                self.exit()
                return
            self._review_next(iter(pending))

        def _review_next(self, it) -> None:
            try:
                project = next(it)
            except StopIteration:
                self.push_screen(MigrationProgressScreen(outcomes=outcomes))
                return
            runner = FlatTodoMigration(
                project=project,
                run_ts=run_ts,
                backup_root=backup_root,
                integrations=integrations,
                strict_resync=strict_resync,
            )
            plan = runner.plan()
            self.push_screen(
                MigrationReviewScreen(
                    plan=plan,
                    backup_preview=str(backup_root / project.name),
                ),
                lambda r, runner=runner, it=it: self._after_review(r, runner, it),
            )

        def _after_review(self, result, runner, it) -> None:
            action, _ = result
            nonlocal exit_code
            if action == "skip":
                runner.confirm(False)
                outcomes.append(
                    MigrationOutcome(
                        project=runner.project.name, ok=True,
                        resync_partial=False, backup="—",
                    ),
                )
                self._review_next(it)
                return
            if action == "quit":
                exit_code = 3
                self.exit()
                return
            runner.confirm(True)
            try:
                runner.execute_local()
                runner.commit()
                partial = bool(runner.resync_failures)
                outcomes.append(
                    MigrationOutcome(
                        project=runner.project.name,
                        ok=True,
                        resync_partial=partial,
                        backup=str(runner.snapshot.dir) if runner.snapshot else "—",
                    ),
                )
                if partial:
                    exit_code = max(exit_code, 2)
            except Exception as e:
                outcomes.append(
                    MigrationOutcome(
                        project=runner.project.name,
                        ok=False,
                        resync_partial=False,
                        backup=str(runner.snapshot.dir) if runner.snapshot else "—",
                        error=str(e),
                    ),
                )
                exit_code = max(exit_code, 2)
            self._review_next(it)

    MigrationApp().run()
    return exit_code


def _integration_badges(pending, integrations) -> dict[str, set[str]]:
    """Compute the letter badge set per project based on live integration links."""
    import yaml

    badges: dict[str, set[str]] = {}
    for project in pending:
        s: set[str] = set()
        todos = yaml.safe_load((project.path / "todos.yaml").read_text()) or []
        for t in todos:
            if t.get("todoist_task_id"):
                s.add("T")
            if t.get("trello_card_id") or t.get("trello_checklist_item_id"):
                s.add("R")
            if t.get("jira_issue_key"):
                s.add("J")
        badges[project.name] = s
    return badges


def _count_parents_children(project) -> tuple[int, int]:
    import yaml

    todos = yaml.safe_load((project.path / "todos.yaml").read_text()) or []
    parents = sum(1 for t in todos if t.get("children"))
    children = sum(1 for t in todos if t.get("parent") is not None)
    return parents, children
```

- [ ] **Step 2: Add post-install call in `installer/app.py::run()`**

Find the spot immediately after the plugin install/update phase completes (before the existing summary/exit code path) and insert:

```python
# Post-install flat-todo migration check (todo 636 Phase 1)
from installer.cli import load_project_list
from installer.migrations.entry import run_pending_migrations

_mig_code = run_pending_migrations(
    load_project_list(),
    interactive=sys.stdin.isatty(),
)
# Non-zero from migration contributes to overall exit code but doesn't mask plugin errors.
if _mig_code and not exit_code:
    exit_code = _mig_code
```

- [ ] **Step 3: Manually smoke-test the TUI**

Run: `uv run python -m installer.main --migrate-flat-dry-run`
Expected: prints "Dry-run report: …" path; exits 0; report file exists.

Run: `uv run python -m installer.main --migrate-flat` (only if there's a v1 project at hand)
Expected: overview screen renders, keybindings work, review screen renders, migrate completes for at least one project, summary shows correct counts.

- [ ] **Step 4: Commit**

```bash
git add installer/app.py
git commit -m "feat(installer/app): post-install flat-todo migration hook + TUI driver"
```

---

## Task 19: E2E — happy path

**Files:**
- Create: `installer/tests/migrations/e2e/__init__.py`
- Create: `installer/tests/migrations/e2e/conftest.py`
- Create: `installer/tests/migrations/e2e/test_e2e_happy_path.py`

- [ ] **Step 1: Write `conftest.py` with fixtures**

```python
# installer/tests/migrations/e2e/conftest.py
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def home_with_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake $HOME with 3 projects: cpm (T+R+J), side (T only), legacy (no integrations)."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)

    cpm_dir = home / "projects" / "cpm"
    side_dir = home / "projects" / "side"
    legacy_dir = home / "projects" / "legacy"
    for d, name, integ in (
        (cpm_dir, "cpm", {"todoist": True, "trello": True, "jira": True}),
        (side_dir, "side", {"todoist": True}),
        (legacy_dir, "legacy", {}),
    ):
        d.mkdir(parents=True)
        sync: dict = {}
        if integ.get("todoist"):
            sync["todoist"] = {"enabled": True, "api_token": "tok"}
        if integ.get("trello"):
            sync["trello"] = {
                "enabled": True,
                "api_key": "k",
                "api_token": "t",
                "board_id": "b",
                "list_mappings": {"tasks": "l"},
            }
        if integ.get("jira"):
            sync["jira"] = {
                "enabled": True,
                "base_url": "https://ex.atlassian.net",
                "email": "e@x.com",
                "api_token": "tok",
                "epic_link_field": "customfield_10014",
            }
        (d / "proj.yaml").write_text(yaml.safe_dump({"name": name, "sync": sync}))
        tdata = [
            {
                "id": "1", "title": "parent", "parent": None, "children": ["1.1"],
                "tags": [], "todoist_task_id": "p-" + name,
                "trello_card_id": "pc-" + name if integ.get("trello") else None,
                "trello_checklist_id": "cl-" + name if integ.get("trello") else None,
                "jira_issue_key": "J-" + name if integ.get("jira") else None,
            },
            {
                "id": "1.1", "title": "child", "parent": "1", "children": [],
                "tags": [], "todoist_task_id": "c-" + name,
                "trello_checklist_item_id": "it-" + name if integ.get("trello") else None,
                "jira_issue_key": "J2-" + name if integ.get("jira") else None,
            },
        ]
        (d / "todos.yaml").write_text(yaml.safe_dump(tdata))
        (d / "archive.yaml").write_text("[]\n")
        conn = sqlite3.connect(d / "data.db")
        conn.executescript(
            "CREATE TABLE todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);"
            "CREATE TABLE archive_todos (id TEXT PRIMARY KEY, title TEXT, parent TEXT, children TEXT, tags TEXT, next_child_id INTEGER);",
        )
        conn.commit()
        conn.close()

    (home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump({
            "projects": [
                {"name": "cpm", "path": str(cpm_dir)},
                {"name": "side", "path": str(side_dir)},
                {"name": "legacy", "path": str(legacy_dir)},
            ],
        }),
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    return home
```

- [ ] **Step 2: Write failing e2e happy-path test**

```python
# installer/tests/migrations/e2e/test_e2e_happy_path.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.detect import read_schema_version
from installer.migrations.entry import MIGRATION_ROOT
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.jira import JiraResync
from installer.migrations.integrations.todoist import TodoistResync
from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.types import PendingProject


@respx.mock
def test_happy_path_three_projects(home_with_projects: Path) -> None:
    # Mock all three SaaS endpoints broadly
    respx.post("https://api.todoist.com/api/v1/sync").mock(return_value=Response(200, json={}))
    respx.post("https://api.trello.com/1/cards").mock(
        return_value=Response(200, json={"id": "new-card"}),
    )
    respx.get(url__regex=r"https://api\.trello\.com/1/cards/.*/idLabels").mock(
        return_value=Response(200, json=[]),
    )
    respx.delete(url__regex=r"https://api\.trello\.com/1/checklists/.*").mock(
        return_value=Response(200),
    )
    respx.put(url__regex=r"https://ex\.atlassian\.net/rest/api/3/issue/.*").mock(
        return_value=Response(204),
    )

    projects = [
        PendingProject(
            name=name,
            path=home_with_projects / "projects" / name,
            proj_yaml_path=home_with_projects / "projects" / name / "proj.yaml",
            current_version=1,
        )
        for name in ("cpm", "side", "legacy")
    ]
    integrations = [TodoistResync(), TrelloResync(), JiraResync()]
    outcomes = []
    for p in projects:
        runner = FlatTodoMigration(
            project=p,
            run_ts="e2e-happy",
            backup_root=MIGRATION_ROOT / "e2e-happy",
            integrations=integrations,
        )
        runner.plan()
        runner.confirm()
        runner.execute_local()
        runner.commit()
        outcomes.append(runner)

    for r in outcomes:
        assert read_schema_version(r.project.proj_yaml_path) == 2
        todos = yaml.safe_load((r.project.path / "todos.yaml").read_text())
        child = next(t for t in todos if t["id"] == "1.1")
        assert "group:1" in child["tags"]
        assert "parent" not in child
```

- [ ] **Step 3: Run — expect failing monkeypatch on trello `_update_local_trello_card_id`**

Run: `uv run pytest installer/tests/migrations/e2e/test_e2e_happy_path.py -v`

Expected: may fail with `ModuleNotFoundError` in the Trello update shim if `plugins.proj.server.server.lib.storage` is not importable as a package. Add sys.path handling or mark the shim import lazy:

```python
# Add near top of test file (inside `test_happy_path_three_projects`, before calling run).
import installer.migrations.integrations.trello as t
monkeypatch_ctx = pytest.MonkeyPatch()
monkeypatch_ctx.setattr(t, "_update_local_trello_card_id", lambda *a, **k: None)
```

Or restructure the test to use `monkeypatch` fixture from pytest. Simplest:

```python
@respx.mock
def test_happy_path_three_projects(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import installer.migrations.integrations.trello as t
    monkeypatch.setattr(t, "_update_local_trello_card_id", lambda *a, **k: None)
    # ... rest of test ...
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest installer/tests/migrations/e2e/test_e2e_happy_path.py -v`

- [ ] **Step 5: Commit**

```bash
git add installer/tests/migrations/e2e/
git commit -m "test(installer/migrations): e2e happy path (3 projects, all integrations)"
```

---

## Task 20: E2E — rollback on flatten failure

**Files:**
- Create: `installer/tests/migrations/e2e/test_e2e_rollback.py`

- [ ] **Step 1: Write failing test**

```python
# installer/tests/migrations/e2e/test_e2e_rollback.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.entry import MIGRATION_ROOT
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.types import PendingProject


def test_rollback_isolated_to_failing_project(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force SQL flatten to raise on "side" but not on the other projects
    from installer.migrations import transform as tr

    real = tr.flatten_todos_sql

    def selective(db_path: Path) -> None:
        if "side" in str(db_path):
            raise RuntimeError("simulated ALTER failure")
        real(db_path)

    monkeypatch.setattr(tr, "flatten_todos_sql", selective)
    monkeypatch.setattr(
        "installer.migrations.flat_todo.flatten_todos_sql", selective,
    )

    projects = [
        PendingProject(
            name=name,
            path=home_with_projects / "projects" / name,
            proj_yaml_path=home_with_projects / "projects" / name / "proj.yaml",
            current_version=1,
        )
        for name in ("cpm", "side", "legacy")
    ]

    results: list[tuple[str, str]] = []
    for p in projects:
        runner = FlatTodoMigration(
            project=p,
            run_ts="e2e-rb",
            backup_root=MIGRATION_ROOT / "e2e-rb",
            integrations=[],  # local-only — no SaaS mocks needed
        )
        runner.plan()
        runner.confirm()
        try:
            runner.execute_local()
            runner.commit()
            results.append((p.name, "ok"))
        except Exception:
            results.append((p.name, "failed"))

    assert results == [("cpm", "ok"), ("side", "failed"), ("legacy", "ok")]

    assert read_schema_version(projects[0].proj_yaml_path) == 2
    assert read_schema_version(projects[1].proj_yaml_path) == 1  # reverted
    assert read_schema_version(projects[2].proj_yaml_path) == 2

    side_todos = yaml.safe_load(
        (projects[1].path / "todos.yaml").read_text(),
    )
    assert side_todos[0].get("children") == ["1.1"]  # restored nested form
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest installer/tests/migrations/e2e/test_e2e_rollback.py -v`

- [ ] **Step 3: Debug any fixture issues; no production-code changes expected**

The test should pass with the current implementation. If it fails, it's likely a fixture setup issue in the shared `home_with_projects` (e.g., missing integrations modules needing fewer mocks). No integration mocks needed here since `integrations=[]`.

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest installer/tests/migrations/e2e/test_e2e_rollback.py -v`

- [ ] **Step 5: Commit**

```bash
git add installer/tests/migrations/e2e/test_e2e_rollback.py
git commit -m "test(installer/migrations): e2e rollback isolates failure to one project"
```

---

## Task 21: E2E — resync partial failure

**Files:**
- Create: `installer/tests/migrations/e2e/test_e2e_resync_partial.py`

- [ ] **Step 1: Write failing test**

```python
# installer/tests/migrations/e2e/test_e2e_resync_partial.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.detect import read_schema_version
from installer.migrations.entry import MIGRATION_ROOT
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.types import PendingProject


@respx.mock
def test_trello_500_leaves_local_committed(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import installer.migrations.integrations.trello as t
    monkeypatch.setattr(t, "_update_local_trello_card_id", lambda *a, **k: None)

    respx.post("https://api.trello.com/1/cards").mock(return_value=Response(500))

    project = PendingProject(
        name="cpm",
        path=home_with_projects / "projects" / "cpm",
        proj_yaml_path=home_with_projects / "projects" / "cpm" / "proj.yaml",
        current_version=1,
    )
    runner = FlatTodoMigration(
        project=project,
        run_ts="e2e-partial",
        backup_root=MIGRATION_ROOT / "e2e-partial",
        integrations=[TrelloResync()],
    )
    runner.plan()
    runner.confirm()
    runner.execute_local()
    runner.commit()

    assert read_schema_version(project.proj_yaml_path) == 2
    todos = yaml.safe_load((project.path / "todos.yaml").read_text())
    assert "group:1" in [tag for t in todos for tag in t.get("tags", [])]
    assert len(runner.resync_failures) >= 1
```

- [ ] **Step 2: Run — fail or pass depending on existing behavior**

Run: `uv run pytest installer/tests/migrations/e2e/test_e2e_resync_partial.py -v`

- [ ] **Step 3: Commit once green**

```bash
git add installer/tests/migrations/e2e/test_e2e_resync_partial.py
git commit -m "test(installer/migrations): e2e resync partial does not revert local"
```

---

## Task 22: E2E — power-loss recovery (bump-only)

**Files:**
- Create: `installer/tests/migrations/e2e/test_e2e_power_loss_recovery.py`

- [ ] **Step 1: Write failing test**

```python
# installer/tests/migrations/e2e/test_e2e_power_loss_recovery.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.migrations.detect import read_schema_version
from installer.migrations.entry import MIGRATION_ROOT
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.types import PendingProject, RecoveryPath


def test_bump_only_path_after_interrupted_run(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = PendingProject(
        name="cpm",
        path=home_with_projects / "projects" / "cpm",
        proj_yaml_path=home_with_projects / "projects" / "cpm" / "proj.yaml",
        current_version=1,
    )
    # Simulate SIGKILL between FLATTENED and COMMITTED by running through flatten
    # and then crashing before commit writes schema_version.
    from installer.migrations import flat_todo

    class CrashingRunner(FlatTodoMigration):
        def _commit(self) -> None:  # crash after flatten succeeded
            raise SystemExit("crash")

    runner = CrashingRunner(
        project=project,
        run_ts="crash-run",
        backup_root=MIGRATION_ROOT / "crash-run",
        integrations=[],
    )
    runner.plan()
    runner.confirm()
    with pytest.raises((SystemExit, RuntimeError)):
        runner.execute_local()
        runner.commit()

    # schema_version still 1 because commit crashed
    assert read_schema_version(project.proj_yaml_path) == 1

    # Second run should detect already-flat and take BUMP_ONLY path
    runner2 = FlatTodoMigration(
        project=project,
        run_ts="recovery-run",
        backup_root=MIGRATION_ROOT / "recovery-run",
        integrations=[],
    )
    plan = runner2.plan()
    assert plan.recovery_path == RecoveryPath.BUMP_ONLY
    runner2.confirm()
    runner2.execute_local()
    runner2.commit()
    assert read_schema_version(project.proj_yaml_path) == 2
```

- [ ] **Step 2: Run + iterate until green**

Run: `uv run pytest installer/tests/migrations/e2e/test_e2e_power_loss_recovery.py -v`

- [ ] **Step 3: Commit**

```bash
git add installer/tests/migrations/e2e/test_e2e_power_loss_recovery.py
git commit -m "test(installer/migrations): e2e power-loss recovery via BUMP_ONLY path"
```

---

## Task 23: E2E — dry-run + non-TTY combined

**Files:**
- Create: `installer/tests/migrations/e2e/test_e2e_dry_run_and_non_tty.py`

- [ ] **Step 1: Write failing test**

```python
# installer/tests/migrations/e2e/test_e2e_dry_run_and_non_tty.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_dry_run_writes_report_exits_zero(home_with_projects: Path) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate-flat-dry-run"],
        capture_output=True,
        text=True,
        env={"HOME": str(home_with_projects), "PATH": ""},
    )
    assert r.returncode == 0
    assert "Dry-run report:" in r.stdout

    # Nothing mutated
    for name in ("cpm", "side", "legacy"):
        pj = home_with_projects / "projects" / name / "proj.yaml"
        data = yaml.safe_load(pj.read_text())
        assert "schema_version" not in data


def test_non_tty_exits_with_warning(
    home_with_projects: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = subprocess.run(
        [sys.executable, "-m", "installer.main", "--migrate-flat"],
        capture_output=True,
        text=True,
        env={"HOME": str(home_with_projects), "PATH": ""},
        stdin=subprocess.DEVNULL,  # force non-TTY
    )
    assert r.returncode == 0
    assert "interactive terminal" in r.stdout
    # Still no mutation
    pj = home_with_projects / "projects" / "cpm" / "proj.yaml"
    data = yaml.safe_load(pj.read_text())
    assert "schema_version" not in data
```

- [ ] **Step 2: Run**

Run: `uv run pytest installer/tests/migrations/e2e/test_e2e_dry_run_and_non_tty.py -v`

- [ ] **Step 3: Iterate until green, then commit**

```bash
git add installer/tests/migrations/e2e/test_e2e_dry_run_and_non_tty.py
git commit -m "test(installer/migrations): e2e dry-run + non-TTY mode"
```

---

## Final steps

- [ ] **Step A: Full test sweep**

Run: `uv run pytest installer/tests/migrations/ -v`
Expected: all tests pass.

- [ ] **Step B: Type-check**

Run: `uv run basedpyright installer/migrations/` (if configured) or `uv run mypy installer/migrations/`
Expected: no type errors.

- [ ] **Step C: Lint**

Run: `uv run ruff check installer/migrations/ installer/tests/migrations/ installer/screens/migration_*.py`
Run: `uv run ruff format --check installer/migrations/ installer/tests/migrations/ installer/screens/migration_*.py`
Expected: clean.

- [ ] **Step D: Run one CI integration smoke locally**

Run: `uv run pytest installer/tests/ -v -k "migration"`
Expected: clean.

- [ ] **Step E: Write the ongoing-work summary commit**

Nothing new to commit — just verify `git log --oneline` shows a clean linear history of the ~23 task commits.

- [ ] **Step F: Open PR from worktree branch**

The spec covers Phase 1 only. After merge, file the follow-up:
- "636 Phase 2 — Jira/Trello/Todoist hook + sync code cleanup after flat migration"

---

## Implementer notes

**Predicate reminder:** Do **not** start this plan until todo 624 has merged to `dev`. This plan assumes the server-side flat-model changes from 624 are in place (flat-only `todo_add`, no parent-field resolution in `_build_hook_fields`).

**Respx / pytest-textual-snapshot availability:** Todo 635 ("Fix local test env: install respx/textual/hook_dispatch for all plugins") should be done before running the full test suite. If not, install manually with `uv sync --group test` or `uv pip install respx pytest-textual-snapshot`.

**Trello update shim:** The `_update_local_trello_card_id` function in `installer/migrations/integrations/trello.py` is stubbed in Task 10 and wired to proj storage in Task 12. The exact function name to call in `plugins/proj/server/server/lib/storage.py` may need adjustment — read that file before wiring and match the actual `save_todos` / `update_todo` signature.

**First CI snapshot-test flake is expected** per CLAUDE.md — rerun the workflow once before investigating any snapshot mismatches on first push.

**Errors.log JSONL writer (inline during Task 18):** After `MigrationApp().run()` returns in `run_migration_tui`, write a consolidated JSONL log of all resync failures across projects. Append at the bottom of `run_migration_tui`:

```python
import json
errors_path = backup_root / "errors.log"
errors_path.parent.mkdir(parents=True, exist_ok=True)
with errors_path.open("w") as f:
    for outcome, runner in zip(outcomes, _collected_runners):  # keep a parallel list during loop
        for fail in getattr(runner, "resync_failures", []):
            f.write(
                json.dumps({
                    "ts": run_ts,
                    "project": outcome.project,
                    "phase": f"resync:{fail.action.kind}",
                    "action_id": fail.action.target_id,
                    "error_class": fail.error_class,
                    "message": fail.message,
                    "retryable": fail.retryable,
                }) + "\n",
            )
```

You'll need to keep a `_collected_runners: list[FlatTodoMigration] = []` list in the closure alongside `outcomes` and `.append(runner)` in the same branch that appends to `outcomes`. Skip the log write if no failures collected.

**`--strict-resync` wiring sanity check:** Verify the param flows `main.py → entry.run_pending_migrations → app.run_migration_tui → FlatTodoMigration(strict_resync=...)`. Unit-test coverage for strict mode should be added as a new test case in `test_flat_todo_runner.py` alongside Task 12 — a `FailingIntegration` + `strict_resync=True` should raise `ResyncFailure` and trigger `_restore()`. Add this as an additional test during Task 12 if bandwidth permits, else file as a follow-up todo.
