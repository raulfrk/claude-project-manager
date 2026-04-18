"""Todo ID generation (flat model — child IDs derived from sibling scan)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.lib.models import ProjectMeta, Todo


def next_todo_id(
    meta: ProjectMeta,
    parent: Todo | None = None,
    siblings: list[Todo] | None = None,
) -> str:
    """Return the next todo ID.

    - Root todos (no parent): returns str(meta.next_todo_id) and increments meta.
    - Child todos: returns ``f"{parent.id}.{N}"`` where N is max existing child
      sequence + 1, scanning *siblings* for ids shaped ``f"{parent.id}.<int>"``.
      Does NOT mutate any todo — callers own sibling state.

    *siblings* should be the list of todos already present in the project;
    pass [] for a fresh batch. Raises ValueError if a parent is given but
    siblings is None (prevents silent double-numbering bugs).
    """
    if parent is None:
        tid = str(meta.next_todo_id)
        meta.next_todo_id += 1
        return tid
    if siblings is None:
        raise ValueError("siblings= required when parent is given")
    prefix = f"{parent.id}."
    max_seen = 0
    for s in siblings:
        if not s.id.startswith(prefix):
            continue
        tail = s.id[len(prefix) :]
        # Only count direct children (no further dots)
        if "." in tail:
            continue
        try:
            n = int(tail)
        except ValueError:
            continue
        max_seen = max(max_seen, n)
    return f"{prefix}{max_seen + 1}"
