"""Unit tests for sql_decisions structured CRUD module."""

from __future__ import annotations

from server.lib.db import ensure_db, get_connection
from server.lib.models import Decision, ProjConfig
from server.lib.sql_decisions import (
    append_decision,
    ensure_table,
    load_decisions,
    save_decisions,
)


def test_ensure_table_is_idempotent(cfg: ProjConfig) -> None:
    """ensure_table can be called multiple times without error."""
    db_file = ensure_db(cfg, "demo")
    with get_connection(db_file) as conn:
        ensure_table(conn)
        ensure_table(conn)  # second call must not raise
    decisions = load_decisions(cfg, "demo")
    assert decisions == []


def test_load_decisions_empty_returns_empty_list(cfg: ProjConfig) -> None:
    result = load_decisions(cfg, "demo")
    assert result == []


def test_append_decision_assigns_id(cfg: ProjConfig) -> None:
    d = Decision(timestamp="2026-01-01T00:00:00", text="Use SQLite")
    returned = append_decision(cfg, "demo", d)
    assert returned.id is not None
    assert isinstance(returned.id, int)
    assert returned.id >= 1
    assert returned.text == "Use SQLite"


def test_load_decisions_returns_insertion_order(cfg: ProjConfig) -> None:
    for i in range(3):
        append_decision(
            cfg,
            "demo",
            Decision(timestamp=f"2026-01-0{i + 1}T00:00:00", text=f"Decision {i}"),
        )
    result = load_decisions(cfg, "demo")
    assert len(result) == 3
    assert result[0].text == "Decision 0"
    assert result[1].text == "Decision 1"
    assert result[2].text == "Decision 2"
    assert result[0].id < result[1].id < result[2].id


def test_save_decisions_replaces_all(cfg: ProjConfig) -> None:
    for i in range(3):
        append_decision(
            cfg,
            "demo",
            Decision(timestamp="2026-01-01T00:00:00", text=f"Old {i}"),
        )
    new_decisions = [
        Decision(timestamp="2026-06-01T00:00:00", text="New A"),
        Decision(timestamp="2026-06-02T00:00:00", text="New B"),
    ]
    save_decisions(cfg, "demo", new_decisions)
    result = load_decisions(cfg, "demo")
    assert len(result) == 2
    assert result[0].text == "New A"
    assert result[1].text == "New B"


def test_decision_dataclass_roundtrip(cfg: ProjConfig) -> None:
    """Full roundtrip: all fields preserved across append → load."""
    d = Decision(
        timestamp="2026-03-15T10:30:00",
        text="Switch to SQL-only storage",
        todo_id="647",
        tags=["architecture", "storage"],
    )
    returned = append_decision(cfg, "demo", d)
    assert returned.id is not None

    loaded = load_decisions(cfg, "demo")
    assert len(loaded) == 1
    item = loaded[0]
    assert item.text == "Switch to SQL-only storage"
    assert item.timestamp == "2026-03-15T10:30:00"
    assert item.todo_id == "647"
    assert item.tags == ["architecture", "storage"]
    assert item.id == returned.id
