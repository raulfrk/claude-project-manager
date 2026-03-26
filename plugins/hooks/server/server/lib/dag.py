"""Directed-graph cycle detection for the hook registry."""

from __future__ import annotations

from server.lib.models import Hook


def _build_adjacency(hooks: list[Hook]) -> dict[str, set[str]]:
    """Build an adjacency list from registered hooks (trigger_tool -> target_tool)."""
    graph: dict[str, set[str]] = {}
    for hook in hooks:
        graph.setdefault(hook.trigger_tool, set()).add(hook.target_tool)
        # Ensure target_tool appears as a node even if it has no outgoing edges
        graph.setdefault(hook.target_tool, set())
    return graph


def would_create_cycle(hooks: list[Hook], new_trigger: str, new_target: str) -> bool:
    """Return True if adding an edge new_trigger -> new_target would create a cycle.

    Also rejects self-references (new_trigger == new_target).
    Uses iterative DFS from new_target to see if new_trigger is reachable,
    which would mean the new edge closes a loop.
    """
    if new_trigger == new_target:
        return True

    graph = _build_adjacency(hooks)
    # Temporarily add the new edge's target node (in case it's new)
    graph.setdefault(new_target, set())
    graph.setdefault(new_trigger, set())

    # DFS from new_target: if we can reach new_trigger, adding the edge
    # new_trigger -> new_target would close a cycle.
    visited: set[str] = set()
    stack = [new_target]
    while stack:
        node = stack.pop()
        if node == new_trigger:
            return True
        if node in visited:
            continue
        visited.add(node)
        for neighbour in graph.get(node, set()):
            if neighbour not in visited:
                stack.append(neighbour)

    return False


def find_cycle_path(hooks: list[Hook], new_trigger: str, new_target: str) -> list[str] | None:
    """Return the cycle path if adding new_trigger -> new_target would create one, else None.

    The returned path is a list like [A, B, C, A] showing the cycle.
    Useful for error messages.
    """
    if new_trigger == new_target:
        return [new_trigger, new_target]

    graph = _build_adjacency(hooks)
    graph.setdefault(new_target, set())
    graph.setdefault(new_trigger, set())

    # BFS from new_target to find a path back to new_trigger
    from collections import deque

    parent: dict[str, str | None] = {new_target: None}
    queue: deque[str] = deque([new_target])
    while queue:
        node = queue.popleft()
        for neighbour in graph.get(node, set()):
            if neighbour == new_trigger:
                # Reconstruct path: new_trigger -> new_target -> ... -> neighbour(==new_trigger)
                path = [new_trigger]
                cur: str | None = node
                chain: list[str] = []
                while cur is not None:
                    chain.append(cur)
                    cur = parent.get(cur)
                path.extend(chain)
                path.append(new_trigger)
                return path
            if neighbour not in parent:
                parent[neighbour] = node
                queue.append(neighbour)

    return None


__all__ = ["would_create_cycle", "find_cycle_path"]
