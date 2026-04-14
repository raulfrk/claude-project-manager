"""Tests for server.lib.db — schema, WAL, idempotency, concurrent reads, foreign keys."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from server.lib import db as db_module
from server.lib.db import db_path, ensure_db, get_connection, init_schema
from server.lib.models import ProjConfig


@pytest.fixture()
def tmp_cfg(tmp_path: Path) -> ProjConfig:
    """ProjConfig with tracking_dir pointing at tmp_path/tracking."""
    return ProjConfig(tracking_dir=str(tmp_path / "tracking"))


@pytest.fixture(autouse=True)
def reset_initialized_dbs() -> None:
    """Clear module-level _initialized_dbs set before each test."""
    db_module._initialized_dbs.clear()


# ── Schema ────────────────────────────────────────────────────────────────────


def test_init_schema_creates_all_tables() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        init_schema(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r[0] for r in rows}
        assert {
            "todos",
            "archive_todos",
            "project_meta",
            "project_index",
            "decisions",
        } <= table_names
    finally:
        conn.close()


def test_init_schema_creates_indexes() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        init_schema(conn)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        index_names = {r[0] for r in rows}
        expected = {
            "idx_todos_project",
            "idx_todos_project_status",
            "idx_todos_parent",
            "idx_todos_todoist",
            "idx_todos_trello",
            "idx_todos_jira",
            "idx_archive_project",
            "idx_archive_project_status",
            "idx_decisions_project",
        }
        assert expected <= index_names
    finally:
        conn.close()


# ── WAL + FK ──────────────────────────────────────────────────────────────────


def test_wal_mode_enabled(tmp_cfg: ProjConfig) -> None:
    ensure_db(tmp_cfg, "myproject")
    conn = get_connection(db_path(tmp_cfg, "myproject"))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
    finally:
        conn.close()


def test_foreign_keys_on(tmp_cfg: ProjConfig) -> None:
    ensure_db(tmp_cfg, "myproject")
    conn = get_connection(db_path(tmp_cfg, "myproject"))
    try:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
    finally:
        conn.close()


# ── ensure_db ─────────────────────────────────────────────────────────────────


def test_ensure_db_creates_file(tmp_cfg: ProjConfig) -> None:
    path = db_path(tmp_cfg, "myproject")
    assert not path.exists()
    ensure_db(tmp_cfg, "myproject")
    assert path.exists()


def test_ensure_db_idempotent(tmp_cfg: ProjConfig) -> None:
    ensure_db(tmp_cfg, "myproject")
    ensure_db(tmp_cfg, "myproject")  # second call — must not raise
    conn = get_connection(db_path(tmp_cfg, "myproject"))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r[0] for r in rows}
        assert "todos" in table_names
    finally:
        conn.close()


# ── row_factory ───────────────────────────────────────────────────────────────


def test_get_connection_row_factory(tmp_cfg: ProjConfig) -> None:
    ensure_db(tmp_cfg, "myproject")
    conn = get_connection(db_path(tmp_cfg, "myproject"))
    try:
        conn.execute("INSERT INTO project_meta VALUES ('test', 'data')")
        row = conn.execute("SELECT * FROM project_meta WHERE name='test'").fetchone()
        assert row["name"] == "test"
        assert row["data"] == "data"
    finally:
        conn.close()


# ── Concurrent reads ──────────────────────────────────────────────────────────


def test_concurrent_reads_dont_block(tmp_cfg: ProjConfig) -> None:
    ensure_db(tmp_cfg, "myproject")
    path = db_path(tmp_cfg, "myproject")
    errors: list[Exception] = []
    results: list[list[object]] = []

    def read_todos() -> None:
        try:
            conn = get_connection(path)
            rows = conn.execute("SELECT * FROM todos").fetchall()
            results.append(list(rows))
            conn.close()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=read_todos) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent read errors: {errors}"
    assert len(results) == 10
    assert all(r == [] for r in results)
