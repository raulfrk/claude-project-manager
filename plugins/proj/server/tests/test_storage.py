"""Tests for server.lib.storage."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

import server.lib.migration as _mig
from server.lib import storage
from server.lib.models import ProjConfig, ProjectEntry, ProjectIndex, RepoEntry, Todo


@pytest.fixture(autouse=True)
def clear_migration_cache():
    _mig._migrated_projects.clear()
    yield
    _mig._migrated_projects.clear()


@pytest.fixture()
def tmp_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(cfg)
    return cfg


def test_config_roundtrip(tmp_cfg: ProjConfig, tmp_path: Path) -> None:
    cfg = storage.load_config()
    assert cfg.tracking_dir == tmp_cfg.tracking_dir
    assert cfg.git_integration is True
    assert cfg.default_priority == "medium"


def test_config_exists(tmp_cfg: ProjConfig) -> None:
    assert storage.config_exists()


def test_index_empty_on_missing_file(tmp_cfg: ProjConfig) -> None:
    index = storage.load_index(tmp_cfg)
    assert index.projects == {}


def test_index_roundtrip(tmp_cfg: ProjConfig) -> None:
    index = ProjectIndex(
        projects={
            "myapp": ProjectEntry(name="myapp", tracking_dir="/t/myapp", created="2026-01-01")
        },
    )
    storage.save_index(tmp_cfg, index)
    loaded = storage.load_index(tmp_cfg)
    assert "myapp" in loaded.projects


def test_meta_roundtrip(tmp_cfg: ProjConfig, tmp_path: Path) -> None:
    from server.lib.models import ProjectDates, ProjectMeta

    meta = ProjectMeta(
        name="myapp",
        description="Test project",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created="2026-01-01", last_updated="2026-01-01"),
    )
    storage.save_meta(tmp_cfg, meta)
    loaded = storage.load_meta(tmp_cfg, "myapp")
    assert loaded.name == "myapp"
    assert loaded.description == "Test project"
    assert loaded.dates.last_updated == str(date.today())  # save_meta bumps this


def test_todos_roundtrip(tmp_cfg: ProjConfig) -> None:
    from server.lib.models import Todo

    # Create project dir first
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    todos = [
        Todo(id="T001", title="First", created="2026-01-01", updated="2026-01-01"),
        Todo(
            id="T002",
            title="Second",
            tags=["group:T001"],
            created="2026-01-01",
            updated="2026-01-01",
        ),
    ]
    storage.save_todos(tmp_cfg, "myapp", todos)
    loaded = storage.load_todos(tmp_cfg, "myapp")
    assert len(loaded) == 2
    assert loaded[0].id == "T001"
    assert loaded[1].id == "T002"
    # Flat model: parent membership via group:<id> tag, no .parent field
    assert "group:T001" in loaded[1].tags


def test_append_note_creates_file(tmp_cfg: ProjConfig) -> None:
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    storage.append_note(tmp_cfg, "myapp", "First note")
    storage.append_note(tmp_cfg, "myapp", "Second note")
    notes = storage.read_notes(tmp_cfg, "myapp")
    assert "First note" in notes
    assert "Second note" in notes


def test_requirements_roundtrip(tmp_cfg: ProjConfig) -> None:
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    storage.write_requirements(tmp_cfg, "myapp", "T001", "# Requirements\n\nGoal: do something")
    content = storage.read_requirements(tmp_cfg, "myapp", "T001")
    assert content is not None
    assert "Goal" in content


def test_research_roundtrip(tmp_cfg: ProjConfig) -> None:
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    storage.write_research(tmp_cfg, "myapp", "T001", "# Research\n\nApproach: X")
    content = storage.read_research(tmp_cfg, "myapp", "T001")
    assert content is not None
    assert "Approach" in content


class TestLoadYaml:
    """Tests for _load_yaml() edge cases: corrupt YAML and non-dict top-level values."""

    def test_corrupt_yaml_returns_empty_dict(self, tmp_path: Path) -> None:
        corrupt_file = tmp_path / "corrupt.yaml"
        corrupt_file.write_text("key: [unbalanced\n")
        result = storage._load_yaml(corrupt_file)
        assert result == {}

    def test_scalar_top_level_returns_empty_dict(self, tmp_path: Path) -> None:
        scalar_file = tmp_path / "scalar.yaml"
        scalar_file.write_text("42\n")
        result = storage._load_yaml(scalar_file)
        assert result == {}

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.yaml"
        result = storage._load_yaml(missing)
        assert result == {}

    def test_valid_dict_yaml_returns_dict(self, tmp_path: Path) -> None:
        valid_file = tmp_path / "valid.yaml"
        valid_file.write_text("key: value\nnumber: 42\n")
        result = storage._load_yaml(valid_file)
        assert result == {"key": "value", "number": 42}


class TestRenameTodoDir:
    def test_rename_existing_dir_returns_true(self, tmp_cfg: ProjConfig) -> None:
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
        old_dir = storage.todo_content_dir(tmp_cfg, "myapp", "T001")
        old_dir.mkdir(parents=True)
        (old_dir / "requirements.md").write_text("# Reqs\n")

        result = storage.rename_todo_dir(tmp_cfg, "myapp", "T001", "1")

        assert result is True

    def test_rename_existing_dir_moves_contents(self, tmp_cfg: ProjConfig) -> None:
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
        old_dir = storage.todo_content_dir(tmp_cfg, "myapp", "T002")
        old_dir.mkdir(parents=True)
        (old_dir / "research.md").write_text("# Research\n")

        storage.rename_todo_dir(tmp_cfg, "myapp", "T002", "2")

        new_dir = storage.todo_content_dir(tmp_cfg, "myapp", "2")
        assert new_dir.exists()
        assert (new_dir / "research.md").exists()
        assert not old_dir.exists()

    def test_rename_nonexistent_dir_returns_false(self, tmp_cfg: ProjConfig) -> None:
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)

        result = storage.rename_todo_dir(tmp_cfg, "myapp", "T999", "99")

        assert result is False
        new_dir = storage.todo_content_dir(tmp_cfg, "myapp", "99")
        assert not new_dir.exists()


class TestConcurrentWrites:
    """Verify atomic write behaviour under concurrent access."""

    def _make_todos(self, prefix: str, count: int = 5) -> list[Todo]:
        return [
            Todo(
                id=f"{prefix}{i}",
                title=f"Todo {prefix}{i}",
                created="2026-01-01",
                updated="2026-01-01",
            )
            for i in range(count)
        ]

    def test_two_concurrent_writes_leave_valid_yaml(self, tmp_cfg: ProjConfig) -> None:
        """Two threads simultaneously calling save_todos must not corrupt the DB."""
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)

        errors: list[Exception] = []

        def write_a() -> None:
            try:
                storage.save_todos(tmp_cfg, "myapp", self._make_todos("A"))
            except Exception as exc:
                errors.append(exc)

        def write_b() -> None:
            try:
                storage.save_todos(tmp_cfg, "myapp", self._make_todos("B"))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=write_a)
        t2 = threading.Thread(target=write_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Unexpected exceptions during concurrent writes: {errors}"

        loaded = storage.load_todos(tmp_cfg, "myapp")
        assert len(loaded) > 0, "At least one write must have persisted todos"
        assert all(isinstance(t, Todo) for t in loaded), "All items must be Todo instances"

    def test_two_concurrent_writes_one_wins_completely(self, tmp_cfg: ProjConfig) -> None:
        """After concurrent writes, SQLite contains exactly one writer's complete data.

        SQLite WAL mode serialises concurrent writes, so both writers succeed and
        the last writer's data is in the DB.  The test verifies:
          - no exceptions from either writer
          - loaded todos are a valid list of Todo instances
        """
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)

        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def write_a() -> None:
            barrier.wait()
            try:
                storage.save_todos(tmp_cfg, "myapp", self._make_todos("A", count=10))
            except Exception as exc:
                errors.append(exc)

        def write_b() -> None:
            barrier.wait()
            try:
                storage.save_todos(tmp_cfg, "myapp", self._make_todos("B", count=10))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=write_a)
        t2 = threading.Thread(target=write_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Writers raised exceptions: {errors}"

        loaded = storage.load_todos(tmp_cfg, "myapp")
        assert len(loaded) > 0, "At least one write must have persisted todos"
        ids = {t.id for t in loaded}

        # All IDs must belong to one writer only — no mixing of A and B data
        all_a = all(tid.startswith("A") for tid in ids)
        all_b = all(tid.startswith("B") for tid in ids)
        assert all_a or all_b, (
            f"DB contains mixed data from both writers, indicating corruption: {ids}"
        )

    def test_read_during_write_returns_consistent_snapshot(self, tmp_cfg: ProjConfig) -> None:
        """A load_todos call concurrent with a save_todos must return a consistent snapshot."""
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)

        # Seed an initial valid state so the reader always has something to find
        initial_todos = self._make_todos("INIT", count=3)
        storage.save_todos(tmp_cfg, "myapp", initial_todos)

        read_results: list[list[Todo]] = []
        read_errors: list[Exception] = []
        write_errors: list[Exception] = []
        iterations = 50

        def writer() -> None:
            for i in range(iterations):
                try:
                    storage.save_todos(tmp_cfg, "myapp", self._make_todos(f"W{i}_", count=4))
                except Exception as exc:
                    write_errors.append(exc)

        def reader() -> None:
            for _ in range(iterations):
                try:
                    todos = storage.load_todos(tmp_cfg, "myapp")
                    read_results.append(todos)
                except Exception as exc:
                    read_errors.append(exc)

        t_write = threading.Thread(target=writer)
        t_read = threading.Thread(target=reader)
        t_write.start()
        t_read.start()
        t_write.join()
        t_read.join()

        assert write_errors == [], f"Writer raised exceptions: {write_errors}"
        assert read_errors == [], f"Reader raised exceptions: {read_errors}"

        # Every snapshot that was read must be a valid list (possibly empty if
        # the file was momentarily absent, but never a partially written structure)
        for snapshot in read_results:
            assert isinstance(snapshot, list), f"Expected list, got {type(snapshot)}"
            for todo in snapshot:
                assert isinstance(todo, Todo), f"Expected Todo instance, got {type(todo)}"


class TestArchiveAndRemoveTodos:
    """Tests for archive_and_remove_todos() atomic staged-write helper."""

    def _make_todo(self, tid: str, title: str) -> Todo:
        return Todo(id=tid, title=title, created="2026-01-01", updated="2026-01-01")

    def test_happy_path_archives_and_removes(self, tmp_cfg: ProjConfig) -> None:
        """Normal completion: todo disappears from active and appears in archive."""
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
        todo = self._make_todo("1", "Task")
        storage.save_todos(tmp_cfg, "myapp", [todo])

        storage.archive_and_remove_todos(tmp_cfg, "myapp", remaining=[], to_archive=[todo])

        active = storage.load_todos(tmp_cfg, "myapp")
        archived = storage.load_archived_todos(tmp_cfg, "myapp")
        assert active == []
        assert len(archived) == 1
        assert archived[0].id == "1"

    def test_existing_archive_entries_are_preserved(self, tmp_cfg: ProjConfig) -> None:
        """Pre-existing archive entries are kept when new ones are appended."""
        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
        old = self._make_todo("old", "Old task")
        storage.save_archived_todos(tmp_cfg, "myapp", [old])
        new_todo = self._make_todo("new", "New task")

        storage.archive_and_remove_todos(tmp_cfg, "myapp", remaining=[], to_archive=[new_todo])

        archived = storage.load_archived_todos(tmp_cfg, "myapp")
        ids = {t.id for t in archived}
        assert ids == {"old", "new"}

    def test_transaction_failure_rolls_back_completely(self, tmp_cfg: ProjConfig) -> None:
        """If archive_and_remove_todos raises mid-transaction, SQLite rolls back entirely.

        SQLite transactions are all-or-nothing: a simulated connection error before any
        writes begin must leave both active and archive tables unchanged (todo stays in
        active, archive stays empty).
        """
        from server.lib.db import get_connection

        (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
        todo = self._make_todo("42", "Important task")
        storage.save_todos(tmp_cfg, "myapp", [todo])

        call_count = 0
        original_get_connection = get_connection

        def get_connection_side_effect(db_file):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("simulated DB connection error")
            return original_get_connection(db_file)

        with (
            patch("server.lib.sql_archive.get_connection", get_connection_side_effect),
            pytest.raises(OSError, match="simulated DB connection error"),
        ):
            storage.archive_and_remove_todos(tmp_cfg, "myapp", remaining=[], to_archive=[todo])

        # Connection failed before writes — todo must still be in active, archive must be empty
        active = storage.load_todos(tmp_cfg, "myapp")
        assert any(t.id == "42" for t in active), (
            "Todo must remain in active when archive operation fails"
        )
        archived = storage.load_archived_todos(tmp_cfg, "myapp")
        assert not any(t.id == "42" for t in archived), (
            "Archive must be empty when archive operation fails before writing"
        )


# ── New SQLite-specific tests ──────────────────────────────────────────────────


def test_save_load_todos_sqlite(tmp_cfg: ProjConfig) -> None:
    """Save 5 todos via save_todos, load via load_todos, assert all 5 present w/ correct fields."""
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    todos = [
        Todo(
            id=f"T{i:03d}",
            title=f"Todo number {i}",
            created="2026-01-01",
            updated="2026-01-01",
        )
        for i in range(1, 6)
    ]
    storage.save_todos(tmp_cfg, "myapp", todos)
    loaded = storage.load_todos(tmp_cfg, "myapp")
    assert len(loaded) == 5
    loaded_ids = {t.id for t in loaded}
    assert loaded_ids == {f"T{i:03d}" for i in range(1, 6)}
    loaded_titles = {t.title for t in loaded}
    assert loaded_titles == {f"Todo number {i}" for i in range(1, 6)}


def test_load_todos_missing_db_raises(tmp_cfg: ProjConfig) -> None:
    """Brand-new project dir with no data.db — load_todos raises FileNotFoundError.

    No YAML fallback.
    """
    (Path(tmp_cfg.tracking_dir) / "brand_new").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match=r"data\.db not found"):
        storage.load_todos(tmp_cfg, "brand_new")


def test_archive_atomicity(tmp_cfg: ProjConfig) -> None:
    """archive_and_remove_todos with 2 to_archive + 3 remaining: archive has 2, active has 3."""
    (Path(tmp_cfg.tracking_dir) / "myapp").mkdir(parents=True)
    all_todos = [
        Todo(id=f"T{i}", title=f"Task {i}", created="2026-01-01", updated="2026-01-01")
        for i in range(1, 6)
    ]
    storage.save_todos(tmp_cfg, "myapp", all_todos)

    to_archive = all_todos[:2]  # T1, T2
    remaining = all_todos[2:]  # T3, T4, T5

    storage.archive_and_remove_todos(tmp_cfg, "myapp", remaining=remaining, to_archive=to_archive)

    active = storage.load_todos(tmp_cfg, "myapp")
    archived = storage.load_archived_todos(tmp_cfg, "myapp")

    assert len(active) == 3, f"Expected 3 active todos, got {len(active)}"
    assert len(archived) == 2, f"Expected 2 archived todos, got {len(archived)}"
    active_ids = {t.id for t in active}
    archived_ids = {t.id for t in archived}
    assert active_ids == {"T3", "T4", "T5"}
    assert archived_ids == {"T1", "T2"}
