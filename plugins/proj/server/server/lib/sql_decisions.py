"""Decisions CRUD via SQLite — append-only, ordered by insertion (id ASC)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from server.lib.db import ensure_db, get_connection

if TYPE_CHECKING:
    from server.lib.models import ProjConfig


def load_decisions(cfg: ProjConfig, project_name: str) -> list[dict[str, object]]:
    """Load all decisions for project, ordered by insertion order (id ASC).

    Returns [] if none found.
    """
    db_file = ensure_db(cfg, project_name)
    with get_connection(db_file) as conn:
        rows = conn.execute(
            "SELECT data FROM decisions WHERE project=? ORDER BY id ASC",
            (project_name,),
        ).fetchall()
    return [json.loads(row["data"]) for row in rows]


def append_decision(cfg: ProjConfig, project_name: str, entry: dict[str, object]) -> None:
    """Append a single decision entry — no read+rewrite cycle, just INSERT."""
    timestamp = entry.get("timestamp") or datetime.now(UTC).isoformat()
    db_file = ensure_db(cfg, project_name)
    with get_connection(db_file) as conn:
        conn.execute(
            "INSERT INTO decisions (project, timestamp, data) VALUES (?, ?, ?)",
            (project_name, timestamp, json.dumps(entry)),
        )


def replace_decisions(cfg: ProjConfig, project_name: str, entries: list[dict[str, object]]) -> None:
    """Replace all decisions for a project atomically (DELETE + INSERT)."""
    db_file = ensure_db(cfg, project_name)
    with get_connection(db_file) as conn:
        conn.execute("DELETE FROM decisions WHERE project=?", (project_name,))
        for entry in entries:
            timestamp = entry.get("timestamp") or datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO decisions (project, timestamp, data) VALUES (?, ?, ?)",
                (project_name, timestamp, json.dumps(entry)),
            )


def load_all_decisions(cfg: ProjConfig) -> dict[str, list[dict[str, object]]]:
    """Load decisions for ALL projects (used by SQLite→YAML export).

    Returns {project_name: [decisions...]} ordered by project then id.
    """
    from pathlib import Path

    tracking = Path(cfg.tracking_dir).expanduser()
    result: dict[str, list[dict[str, object]]] = {}

    if not tracking.exists():
        return result

    for db_file in sorted(tracking.glob("*/data.db")):
        with get_connection(db_file) as conn:
            rows = conn.execute(
                "SELECT project, data FROM decisions ORDER BY project, id"
            ).fetchall()
        for row in rows:
            project = row["project"]
            result.setdefault(project, []).append(json.loads(row["data"]))

    return result
