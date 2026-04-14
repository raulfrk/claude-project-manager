"""SQLite CRUD for project_meta (per-project data.db) and project_index (projects.db)."""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib.db import ensure_db, get_connection
from server.lib.models import (
    JsonDict,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
)

if TYPE_CHECKING:
    from server.lib.models import ProjConfig


# ── Global index DB ───────────────────────────────────────────────────────────

_INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_index (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
"""


def _index_db_path(cfg: ProjConfig) -> Path:
    return Path(cfg.tracking_dir).expanduser() / "projects.db"


def _ensure_index_db(cfg: ProjConfig) -> Path:
    path = _index_db_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    try:
        conn.executescript(_INDEX_SCHEMA)
    finally:
        conn.close()
    return path


# ── Serialization helpers ─────────────────────────────────────────────────────


def _meta_to_dict(meta: ProjectMeta) -> JsonDict:
    """Convert ProjectMeta to JSON-serializable dict via dataclasses.asdict."""
    return dataclasses.asdict(meta)  # type: ignore[return-value]


def _dict_to_meta(data: JsonDict) -> ProjectMeta:
    """Reconstruct ProjectMeta from dict produced by dataclasses.asdict().

    Delegates to ProjectMeta.from_dict which already handles all nested
    reconstruction (RepoEntry, ProjectDates, ProjectPermissions,
    ProjectTodoistConfig, ProjectTrelloConfig, ProjectGitTrackingConfig).
    """
    return ProjectMeta.from_dict(data)


# ── Project metadata (per-project data.db) ────────────────────────────────────


def load_meta(cfg: ProjConfig, project_name: str) -> ProjectMeta:
    """Load project metadata from project_meta table in per-project data.db.

    Raises FileNotFoundError if the project row does not exist.
    """
    db = ensure_db(cfg, project_name)
    conn = get_connection(db)
    try:
        cur = conn.execute("SELECT data FROM project_meta WHERE name=?", (project_name,))
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise FileNotFoundError(f"Project '{project_name}' not found")

    data = json.loads(row["data"])
    return _dict_to_meta(data)


def save_meta(cfg: ProjConfig, meta: ProjectMeta) -> None:
    """Save project metadata to project_meta table in per-project data.db.

    Bumps meta.dates.last_updated to today before persisting.
    """
    meta.dates.last_updated = date.today().isoformat()
    db = ensure_db(cfg, meta.name)
    payload = json.dumps(_meta_to_dict(meta))
    conn = get_connection(db)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO project_meta (name, data) VALUES (?, ?)",
            (meta.name, payload),
        )
    finally:
        conn.close()


# ── Project index (global projects.db) ───────────────────────────────────────


def load_index(cfg: ProjConfig) -> ProjectIndex:
    """Load the full project index from projects.db.

    Returns an empty ProjectIndex if the table has no rows.
    """
    db = _ensure_index_db(cfg)
    conn = get_connection(db)
    try:
        cur = conn.execute("SELECT name, data FROM project_index")
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return ProjectIndex(version=1, projects={})

    projects = {}
    for row in rows:
        entry_data = json.loads(row["data"])
        projects[row["name"]] = ProjectEntry.from_dict(entry_data)

    return ProjectIndex(version=1, projects=projects)


def save_index(cfg: ProjConfig, index: ProjectIndex) -> None:
    """Replace the entire project index atomically in projects.db."""
    db = _ensure_index_db(cfg)
    conn = get_connection(db)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM project_index")
        for name, entry in index.projects.items():
            payload = json.dumps(entry.to_dict())
            conn.execute(
                "INSERT INTO project_index (name, data) VALUES (?, ?)",
                (name, payload),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
