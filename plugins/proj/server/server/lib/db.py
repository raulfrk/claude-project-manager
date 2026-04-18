"""SQLite connection manager, schema initializer, and WAL setup for proj plugin."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.lib.models import ProjConfig

# Module-level tracking of initialized DBs (path string → already initialized).
_initialized_dbs: set[str] = set()
_init_lock = threading.Lock()

# ── Schema ────────────────────────────────────────────────────────────────────

_TODO_COLUMNS = """
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    git_branch TEXT,
    git_commits TEXT NOT NULL DEFAULT '[]',
    blocks TEXT NOT NULL DEFAULT '[]',
    blocked_by TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    has_requirements INTEGER NOT NULL DEFAULT 0,
    has_research INTEGER NOT NULL DEFAULT 0,
    todoist_task_id TEXT,
    todoist_desc_synced TEXT NOT NULL DEFAULT '',
    trello_card_id TEXT,
    trello_checklist_id TEXT,
    trello_checklist_item_id TEXT,
    jira_issue_key TEXT,
    jira_comment_ids TEXT NOT NULL DEFAULT '[]',
    due_date TEXT,
    trello_sync_state TEXT
"""

_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS todos ({_TODO_COLUMNS});

CREATE TABLE IF NOT EXISTS archive_todos ({_TODO_COLUMNS});

CREATE TABLE IF NOT EXISTS project_meta (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_index (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_todos_project ON todos(project);
CREATE INDEX IF NOT EXISTS idx_todos_project_status ON todos(project, status);
CREATE INDEX IF NOT EXISTS idx_todos_todoist ON todos(todoist_task_id);
CREATE INDEX IF NOT EXISTS idx_todos_trello ON todos(trello_card_id);
CREATE INDEX IF NOT EXISTS idx_todos_jira ON todos(jira_issue_key);

CREATE INDEX IF NOT EXISTS idx_archive_project ON archive_todos(project);
CREATE INDEX IF NOT EXISTS idx_archive_project_status ON archive_todos(project, status);

"""

# ── Public API ────────────────────────────────────────────────────────────────


def db_path(cfg: ProjConfig, project_name: str) -> Path:
    """Return path to data.db for this project."""
    tracking_dir = Path(cfg.tracking_dir).expanduser()
    return tracking_dir / project_name / "data.db"


def get_connection(db_file: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode + foreign_keys.

    Settings applied:
    - journal_mode = WAL
    - foreign_keys = ON
    - timeout = 30 (busy wait)
    - isolation_level = None (autocommit; callers manage transactions explicitly)
    - Row factory = sqlite3.Row (named column access)
    """
    conn = sqlite3.connect(str(db_file), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they don't exist. Idempotent."""
    conn.executescript(_SCHEMA_SQL)


def ensure_db(cfg: ProjConfig, project_name: str) -> Path:
    """Ensure data.db exists and schema is initialized. Returns db_path.

    Thread-safe: uses a module-level lock for the init_schema call only.
    After init, concurrent readers/writers are handled by SQLite WAL.
    """
    path = db_path(cfg, project_name)
    path_str = str(path)

    with _init_lock:
        if path_str in _initialized_dbs:
            return path

        path.parent.mkdir(parents=True, exist_ok=True)
        conn = get_connection(path)
        try:
            init_schema(conn)
            from server.lib import sql_decisions as _sd

            _sd.ensure_table(conn)
        finally:
            conn.close()

        _initialized_dbs.add(path_str)

    return path
