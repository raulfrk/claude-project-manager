"""SQLite todos CRUD layer — replaces load_todos/save_todos/load_archived_todos."""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

from server.lib.db import ensure_db, get_connection
from server.lib.models import ProjConfig, Todo, TodoGit, TrelloSyncState

if TYPE_CHECKING:
    import sqlite3


def _todo_to_row(todo: Todo) -> dict[str, object]:
    """Serialize a Todo dataclass to a flat dict of SQL column values.

    Rules:
    - List fields → json.dumps
    - Bool fields (has_requirements, has_research) → int (0/1)
    - git_branch + git_commits → flattened from todo.git
    - trello_sync_state → json.dumps(dataclasses.asdict(tss)) if not None else None
    - 'project' key NOT included — caller must add it
    """
    tss = todo.trello_sync_state
    return {
        "id": todo.id,
        "title": todo.title,
        "status": todo.status,
        "priority": todo.priority,
        "created": todo.created,
        "updated": todo.updated,
        "parent": todo.parent,
        "children": json.dumps(todo.children),
        "next_child_id": todo.next_child_id,
        "tags": json.dumps(todo.tags),
        "git_branch": todo.git.branch,
        "git_commits": json.dumps(todo.git.commits),
        "blocks": json.dumps(todo.blocks),
        "blocked_by": json.dumps(todo.blocked_by),
        "notes": todo.notes,
        "has_requirements": int(todo.has_requirements),
        "has_research": int(todo.has_research),
        "todoist_task_id": todo.todoist_task_id,
        "todoist_desc_synced": todo.todoist_description_synced,
        "trello_card_id": todo.trello_card_id,
        "trello_checklist_id": todo.trello_checklist_id,
        "trello_checklist_item_id": todo.trello_checklist_item_id,
        "jira_issue_key": todo.jira_issue_key,
        "jira_comment_ids": json.dumps(todo.jira_synced_comment_ids),
        "due_date": todo.due_date,
        "trello_sync_state": json.dumps(dataclasses.asdict(tss)) if tss is not None else None,
    }


def _row_to_todo(row: sqlite3.Row) -> Todo:
    """Deserialize a sqlite3.Row into a Todo dataclass.

    Rules:
    - JSON TEXT fields → json.loads
    - INTEGER bool fields → bool()
    - git_branch + git_commits → TodoGit
    - trello_sync_state → TrelloSyncState(**json.loads(...)) if not None
    - 'project' column ignored — not part of Todo
    """
    tss_raw = row["trello_sync_state"]
    tss = TrelloSyncState(**json.loads(tss_raw)) if tss_raw is not None else None

    return Todo(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        priority=row["priority"],
        created=row["created"],
        updated=row["updated"],
        parent=row["parent"],
        children=json.loads(row["children"]),
        next_child_id=row["next_child_id"],
        tags=json.loads(row["tags"]),
        git=TodoGit(
            branch=row["git_branch"],
            commits=json.loads(row["git_commits"]),
        ),
        blocks=json.loads(row["blocks"]),
        blocked_by=json.loads(row["blocked_by"]),
        notes=row["notes"],
        has_requirements=bool(row["has_requirements"]),
        has_research=bool(row["has_research"]),
        todoist_task_id=row["todoist_task_id"],
        todoist_description_synced=row["todoist_desc_synced"],
        trello_card_id=row["trello_card_id"],
        trello_checklist_id=row["trello_checklist_id"],
        trello_checklist_item_id=row["trello_checklist_item_id"],
        jira_issue_key=row["jira_issue_key"],
        jira_synced_comment_ids=json.loads(row["jira_comment_ids"]),
        due_date=row["due_date"],
        trello_sync_state=tss,
    )


# ── Active todos ──────────────────────────────────────────────────────────────


def load_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    """Load active todos from SQLite. Returns [] if project has no todos yet."""
    from server.lib.db import db_path

    path = db_path(cfg, project_name)
    if not path.exists():
        return []

    db_file = ensure_db(cfg, project_name)
    conn = get_connection(db_file)
    try:
        cursor = conn.execute(
            "SELECT * FROM todos WHERE project=? ORDER BY created", (project_name,)
        )
        return [_row_to_todo(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def save_todos(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    """Replace all active todos for this project atomically."""
    db_file = ensure_db(cfg, project_name)
    conn = get_connection(db_file)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM todos WHERE project=?", (project_name,))
        if todos:
            rows = []
            for todo in todos:
                row = _todo_to_row(todo)
                row["project"] = project_name
                rows.append(row)
            # Build INSERT from first row's keys (all rows have same keys)
            cols = list(rows[0].keys())
            placeholders = ", ".join(f":{c}" for c in cols)
            col_names = ", ".join(cols)
            conn.executemany(f"INSERT INTO todos ({col_names}) VALUES ({placeholders})", rows)  # noqa: S608
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ── Archive todos ─────────────────────────────────────────────────────────────


def load_archived_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    """Load archived todos from archive_todos table. Returns [] if db doesn't exist."""
    from server.lib.db import db_path

    path = db_path(cfg, project_name)
    if not path.exists():
        return []

    db_file = ensure_db(cfg, project_name)
    conn = get_connection(db_file)
    try:
        cursor = conn.execute(
            "SELECT * FROM archive_todos WHERE project=? ORDER BY created", (project_name,)
        )
        return [_row_to_todo(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def save_archived_todos_append(
    cfg: ProjConfig, project_name: str, todos_to_add: list[Todo]
) -> None:
    """Append todos to archive_todos table (INSERT only, no delete)."""
    if not todos_to_add:
        return

    db_file = ensure_db(cfg, project_name)
    conn = get_connection(db_file)
    try:
        rows = []
        for todo in todos_to_add:
            row = _todo_to_row(todo)
            row["project"] = project_name
            rows.append(row)
        cols = list(rows[0].keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(cols)
        conn.execute("BEGIN")
        conn.executemany(
            f"INSERT OR REPLACE INTO archive_todos ({col_names}) VALUES ({placeholders})",  # noqa: S608
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
