"""Todo ID generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.lib.models import ProjectMeta, Todo


def next_todo_id(meta: ProjectMeta, parent: "Todo | None" = None) -> str:
    """Return the next todo ID and increment the counter in meta or parent.

    For root todos (no parent): returns str(meta.next_todo_id) e.g. "1", "2", "3".
    For child todos (has parent): returns "{parent.id}.{parent.next_child_id}" e.g. "3.1", "3.2".
    """
    if parent is None:
        tid = str(meta.next_todo_id)
        meta.next_todo_id += 1
    else:
        tid = f"{parent.id}.{parent.next_child_id}"
        parent.next_child_id += 1
    return tid
