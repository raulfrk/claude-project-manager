"""Archive operations via SQLite transactions.

Replaces archive_and_remove_todos and migrate_done_to_archive from storage.py.
Uses a single SQL transaction for atomicity (no dual-tempfile approach).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.db import ensure_db, get_connection
from server.lib.enums import TERMINAL_STATUSES

if TYPE_CHECKING:
    from server.lib.models import ProjConfig, Todo

# ── Row conversion ─────────────────────────────────────────────────────────────


def _todo_to_row(t: Todo, project_name: str) -> tuple[str | int | None, ...]:
    """Convert a Todo to a tuple matching the todos/archive_todos schema column order."""
    git = t.git
    return (
        t.id,
        project_name,
        t.title,
        getattr(t.status, "value", t.status),
        getattr(t.priority, "value", t.priority),
        t.created,
        t.updated,
        t.parent,
        json.dumps(t.children),
        t.next_child_id,
        json.dumps(t.tags),
        git.branch if git else None,
        json.dumps(git.commits if git else []),
        json.dumps(t.blocks),
        json.dumps(t.blocked_by),
        t.notes,
        1 if t.has_requirements else 0,
        1 if t.has_research else 0,
        t.todoist_task_id,
        t.todoist_description_synced,
        t.trello_card_id,
        t.trello_checklist_id,
        t.trello_checklist_item_id,
        t.jira_issue_key,
        json.dumps(t.jira_synced_comment_ids),
        t.due_date,
        json.dumps(t.trello_sync_state.to_dict()) if t.trello_sync_state is not None else None,
    )


_INSERT_COLS = """(
    id, project, title, status, priority, created, updated, parent,
    children, next_child_id, tags, git_branch, git_commits,
    blocks, blocked_by, notes, has_requirements, has_research,
    todoist_task_id, todoist_desc_synced, trello_card_id,
    trello_checklist_id, trello_checklist_item_id, jira_issue_key,
    jira_comment_ids, due_date, trello_sync_state
)"""

_PLACEHOLDERS = "(" + ", ".join(["?"] * 27) + ")"


# ── Public API ─────────────────────────────────────────────────────────────────


def archive_and_remove_todos(
    cfg: ProjConfig,
    project_name: str,
    remaining: list[Todo],
    to_archive: list[Todo],
) -> None:
    """Move todos to archive atomically via single SQL transaction.

    Steps (all within one BEGIN/COMMIT):
    1. INSERT OR REPLACE to_archive into archive_todos
    2. DELETE FROM todos WHERE project=? AND id IN (to_archive IDs)
    3. DELETE FROM todos WHERE project=?  (clear remaining)
    4. INSERT remaining into todos
    """
    db_file = ensure_db(cfg, project_name)
    conn = get_connection(db_file)
    try:
        with conn:  # auto-commit on success, auto-rollback on exception
            # 1. Upsert archived todos into archive_todos
            if to_archive:
                _insert_archive_sql = (
                    f"INSERT OR REPLACE INTO archive_todos {_INSERT_COLS} VALUES {_PLACEHOLDERS}"  # noqa: S608
                )
                conn.executemany(
                    _insert_archive_sql,
                    [_todo_to_row(t, project_name) for t in to_archive],
                )
                archive_ids = [t.id for t in to_archive]
                _placeholders_in = ", ".join(["?"] * len(archive_ids))
                _delete_archive_sql = (
                    f"DELETE FROM todos WHERE project=? AND id IN ({_placeholders_in})"  # noqa: S608
                )
                conn.execute(
                    _delete_archive_sql,
                    [project_name, *archive_ids],
                )

            # 3 & 4. Replace remaining todos (clear + re-insert)
            conn.execute("DELETE FROM todos WHERE project=?", (project_name,))
            if remaining:
                _insert_todos_sql = f"INSERT INTO todos {_INSERT_COLS} VALUES {_PLACEHOLDERS}"  # noqa: S608
                conn.executemany(
                    _insert_todos_sql,
                    [_todo_to_row(t, project_name) for t in remaining],
                )
    finally:
        conn.close()


def migrate_done_to_archive(cfg: ProjConfig, project_name: str) -> dict[str, int]:
    """Move terminal-status todos to archive based on tree rules.

    Tree rules (copied from storage.py):
    - Leaf done/cancelled todos → always archive
    - Done parent where ALL descendants are done/cancelled → archive entire family
    - Done parent with ANY pending/in_progress descendant → keep active
    - Pending/in_progress todos → always keep

    Returns: {"archived_count": N, "remaining_count": M}
    """
    from server.lib import (
        storage,  # late import — storage reads YAML (still valid during transition)
    )

    todos = storage.load_todos(cfg, project_name)
    if not todos:
        return {"archived_count": 0, "remaining_count": 0}

    todo_map = {t.id: t for t in todos}

    def _all_descendants_done(tid: str) -> bool:
        t = todo_map.get(tid)
        if t is None:
            return True
        if t.status not in TERMINAL_STATUSES:
            return False
        return all(_all_descendants_done(cid) for cid in t.children)

    def _collect_family_ids(tid: str) -> set[str]:
        result: set[str] = {tid}
        t = todo_map.get(tid)
        if t:
            for cid in t.children:
                result.update(_collect_family_ids(cid))
        return result

    archive_ids: set[str] = set()

    for t in todos:
        if t.id in archive_ids:
            continue
        if t.status not in TERMINAL_STATUSES:
            continue

        # Leaf (no children, no parent)
        if not t.children and not t.parent:
            archive_ids.add(t.id)
        # Leaf child (no children, has parent)
        elif not t.children and t.parent:
            # Archive child regardless of parent status
            archive_ids.add(t.id)
        # Parent (has children) — only archive when ALL descendants also done
        elif t.children and _all_descendants_done(t.id):
            archive_ids.update(_collect_family_ids(t.id))

    if not archive_ids:
        return {"archived_count": 0, "remaining_count": len(todos)}

    to_archive = [t for t in todos if t.id in archive_ids]
    remaining = [t for t in todos if t.id not in archive_ids]

    # Clean up blocks/blocked_by references to archived IDs in remaining todos
    for t in remaining:
        if any(b in archive_ids for b in t.blocks):
            t.blocks = [b for b in t.blocks if b not in archive_ids]
        if any(b in archive_ids for b in t.blocked_by):
            t.blocked_by = [b for b in t.blocked_by if b not in archive_ids]

    archive_and_remove_todos(cfg, project_name, remaining, to_archive)
    return {"archived_count": len(to_archive), "remaining_count": len(remaining)}
