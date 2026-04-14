"""Concurrent access tests for SQLite WAL layer."""

from __future__ import annotations

import threading

import pytest

import server.lib.migration as _mig
from server.lib import sql_decisions, sql_todos
from server.lib.db import db_path, ensure_db, get_connection
from server.lib.models import ProjConfig, Todo, TodoGit


@pytest.fixture(autouse=True)
def clear_cache():
    _mig._migrated_projects.clear()
    yield
    _mig._migrated_projects.clear()


@pytest.fixture
def tmp_cfg(tmp_path):
    return ProjConfig(tracking_dir=str(tmp_path / "tracking"))


def make_todo(id: str, project: str = "proj") -> Todo:
    return Todo(
        id=id,
        title=f"Todo {id}",
        status="pending",
        priority="medium",
        created="2026-01-01",
        updated="2026-01-01",
        git=TodoGit(),
    )


def test_10_concurrent_writes_no_corruption(tmp_cfg):
    """10 threads each save a todo — no exceptions, db readable after."""
    ensure_db(tmp_cfg, "proj")
    errors: list[Exception] = []
    lock = threading.Lock()

    def write(i: int) -> None:
        try:
            sql_todos.save_todos(tmp_cfg, "proj", [make_todo(str(i))])
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Thread errors: {errors}"
    result = sql_todos.load_todos(tmp_cfg, "proj")
    assert isinstance(result, list)


def test_concurrent_reads_during_write(tmp_cfg):
    """1 writer + 5 readers run simultaneously — no exceptions."""
    ensure_db(tmp_cfg, "proj")
    # Pre-populate
    sql_todos.save_todos(tmp_cfg, "proj", [make_todo(str(i)) for i in range(10)])

    errors: list[Exception] = []
    lock = threading.Lock()

    def writer() -> None:
        try:
            for _ in range(5):
                sql_todos.save_todos(tmp_cfg, "proj", [make_todo("w0")])
        except Exception as e:
            with lock:
                errors.append(e)

    def reader() -> None:
        try:
            for _ in range(10):
                sql_todos.load_todos(tmp_cfg, "proj")
        except Exception as e:
            with lock:
                errors.append(e)

    threads: list[threading.Thread] = [threading.Thread(target=writer)]
    threads += [threading.Thread(target=reader) for _ in range(5)]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Thread errors: {errors}"


def test_wal_concurrent_reads(tmp_cfg):
    """5 threads each open separate connections + read todos — no 'database is locked'."""
    ensure_db(tmp_cfg, "proj")
    db_file = db_path(tmp_cfg, "proj")

    errors: list[Exception] = []
    lock = threading.Lock()

    def read_conn() -> None:
        try:
            conn = get_connection(db_file)
            try:
                conn.execute("SELECT * FROM todos").fetchall()
            finally:
                conn.close()
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=read_conn) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    locked_errors = [e for e in errors if "database is locked" in str(e).lower()]
    assert not locked_errors, f"Got 'database is locked': {locked_errors}"
    assert not errors, f"Thread errors: {errors}"


def test_decisions_append_concurrent(tmp_cfg):
    """10 threads each append 1 decision — final count == 10."""
    ensure_db(tmp_cfg, "proj")
    errors: list[Exception] = []
    lock = threading.Lock()

    def append(i: int) -> None:
        try:
            sql_decisions.append_decision(
                tmp_cfg, "proj", {"key": f"val{i}", "timestamp": "2026-01-01"}
            )
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=append, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Thread errors: {errors}"
    decisions = sql_decisions.load_decisions(tmp_cfg, "proj")
    assert len(decisions) == 10
