# installer/migrations/sql_only_transform.py
"""Transform v2 YAML-hybrid project to v3 SQL-only.

migrate_yaml_to_sql reads todos.yaml / archive.yaml / decisions.yaml from
project_dir, writes rows into the existing data.db, then deletes the YAML
files. Called from SqlOnlyMigration._flatten.

Standalone — no dependency on plugins/proj/server (installer boundary).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Columns sourced from YAML keys (plus `project` injected from project_name).
# These must match _TODO_COLUMNS in db.py for the INSERT to succeed.
_TODO_YAML_FIELDS = (
    "id",
    "title",
    "status",
    "priority",
    "created",
    "updated",
    "tags",
    "git_branch",
    "git_commits",
    "blocks",
    "blocked_by",
    "notes",
    "has_requirements",
    "has_research",
    "todoist_task_id",
    "todoist_desc_synced",
    "trello_card_id",
    "trello_checklist_id",
    "trello_checklist_item_id",
    "jira_issue_key",
    "jira_comment_ids",
    "due_date",
    "trello_sync_state",
)

_TODO_DEFAULTS: dict[str, object] = {
    "status": "pending",
    "priority": "medium",
    "created": "",
    "updated": "",
    "tags": "[]",
    "git_branch": None,
    "git_commits": "[]",
    "blocks": "[]",
    "blocked_by": "[]",
    "notes": "",
    "has_requirements": 0,
    "has_research": 0,
    "todoist_task_id": None,
    "todoist_desc_synced": "",
    "trello_card_id": None,
    "trello_checklist_id": None,
    "trello_checklist_item_id": None,
    "jira_issue_key": None,
    "jira_comment_ids": "[]",
    "due_date": None,
    "trello_sync_state": None,
}


def _list_to_json(val: object) -> str:
    """Normalise a YAML list or JSON-string field to a JSON string."""
    if isinstance(val, list):
        return json.dumps(val)
    if isinstance(val, str):
        return val
    return "[]"


def _todo_row(todo: dict[str, object], project_name: str) -> dict[str, object]:
    """Convert a YAML todo dict to a column→value mapping for INSERT."""
    row: dict[str, object] = {"project": project_name}
    for field in _TODO_YAML_FIELDS:
        raw = todo.get(field, _TODO_DEFAULTS.get(field))
        # Serialise list fields
        if field in {"tags", "git_commits", "blocks", "blocked_by", "jira_comment_ids"}:
            row[field] = _list_to_json(raw)
        else:
            row[field] = raw
    return row


def _load_yaml_list(path: Path) -> list[dict[str, object]]:
    """Load a YAML file that should be a list. Returns [] on missing/invalid.

    Real proj-plugin YAML files for todos + archive use a `{"todos": [...]}`
    wrapper; decisions.yaml is a bare list. Accepts both shapes.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except (FileNotFoundError, yaml.YAMLError):
        return []
    if isinstance(raw, dict):
        # Wrapped form: {"todos": [...]} — todos.yaml + archive.yaml
        for key in ("todos", "decisions", "items"):
            if key in raw and isinstance(raw[key], list):
                raw = raw[key]
                break
        else:
            return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


_FLAT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS todos (
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
);

CREATE TABLE IF NOT EXISTS archive_todos (
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
);

CREATE TABLE IF NOT EXISTS project_meta (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_index (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    text TEXT NOT NULL,
    todo_id TEXT,
    tags TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_todos_project ON todos(project);
CREATE INDEX IF NOT EXISTS idx_todos_project_status ON todos(project, status);
CREATE INDEX IF NOT EXISTS idx_todos_todoist ON todos(todoist_task_id);
CREATE INDEX IF NOT EXISTS idx_todos_trello ON todos(trello_card_id);
CREATE INDEX IF NOT EXISTS idx_todos_jira ON todos(jira_issue_key);
CREATE INDEX IF NOT EXISTS idx_archive_project ON archive_todos(project);
CREATE INDEX IF NOT EXISTS idx_archive_project_status ON archive_todos(project, status);
CREATE INDEX IF NOT EXISTS idx_decisions_todo_id ON decisions(todo_id);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);
"""


def migrate_yaml_to_sql(project_dir: Path) -> None:
    """Read YAML files, write SQL rows, delete YAML files.

    Idempotent: if YAML files are absent the operation is a no-op.
    Ensures flat schema (todos, archive_todos, decisions, project_meta,
    project_index) exists before inserting — handles empty data.db files
    created by prior init steps that never ran schema init.
    Raises on SQL errors (caller should roll back / restore backup).
    """
    db_path = project_dir / "data.db"
    project_name = project_dir.name

    todos_path = project_dir / "todos.yaml"
    archive_path = project_dir / "archive.yaml"
    decisions_path = project_dir / "decisions.yaml"

    todos = _load_yaml_list(todos_path)
    archive = _load_yaml_list(archive_path)
    decisions_raw = _load_yaml_list(decisions_path)

    if not db_path.exists():
        raise FileNotFoundError(
            f"data.db not found at {db_path} — run cpm-install first"
        )

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_FLAT_SCHEMA_SQL)
        conn.execute("BEGIN IMMEDIATE")

        # Insert todos (skip rows already present by id to stay idempotent)
        for todo in todos:
            row = _todo_row(todo, project_name)
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f":{k}" for k in row)
            conn.execute(
                f"INSERT OR IGNORE INTO todos ({cols}) VALUES ({placeholders})",  # noqa: S608
                row,
            )

        # Insert archive
        for todo in archive:
            row = _todo_row(todo, project_name)
            cols = ", ".join(row.keys())
            placeholders = ", ".join(f":{k}" for k in row)
            conn.execute(
                f"INSERT OR IGNORE INTO archive_todos ({cols}) VALUES ({placeholders})",  # noqa: S608
                row,
            )

        # Insert decisions
        for decision in decisions_raw:
            timestamp = str(decision.get("timestamp") or "")
            # Accept 'text' (new) or 'decision' (legacy) key
            text = str(decision.get("text") or decision.get("decision") or "")
            todo_id = str(decision["todo_id"]) if decision.get("todo_id") else None
            tags_raw = decision.get("tags", [])
            tags = json.dumps(tags_raw) if isinstance(tags_raw, list) else "[]"
            conn.execute(
                "INSERT INTO decisions (timestamp, text, todo_id, tags) VALUES (?, ?, ?, ?)",
                (timestamp, text, todo_id, tags),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Delete YAML files only after successful SQL commit
    for path in (todos_path, archive_path, decisions_path):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete %s: %s", path, exc)
