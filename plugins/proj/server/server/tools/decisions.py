"""MCP tool for project decision logging."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


_SEARCH_THRESHOLD = 0.5


def fuzzy_score(query: str, text: str) -> float:
    """Return a 0.0-1.0 similarity score between a query token and text.

    For short queries (< 3 chars) falls back to exact substring containment.
    An exact substring match always returns 1.0; otherwise uses
    SequenceMatcher ratio.
    """
    if len(query) < 3:
        return 1.0 if query.lower() in text.lower() else 0.0
    text_lower = text.lower()
    query_lower = query.lower()
    if query_lower in text_lower:
        return 1.0
    return SequenceMatcher(None, query_lower, text_lower).ratio()


def score_entry(query: str, entry: dict) -> float:  # type: ignore[type-arg]
    """Score a decision entry against a query using token-based fuzzy matching.

    Tokenizes the query, scores each token against all entry fields, and
    returns the mean score across tokens.
    """
    tags = entry.get("tags", [])
    tags_str = " ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
    combined = " ".join(
        str(f)
        for f in [
            entry.get("decision", ""),
            entry.get("context", ""),
            tags_str,
            entry.get("todo_id", ""),
        ]
    )
    tokens = query.split()
    if not tokens:
        return 0.0
    scores = [fuzzy_score(t, combined) for t in tokens]
    return sum(scores) / len(scores)


def register(app: FastMCP) -> None:
    """Register proj_decision_log tool with the MCP app."""

    @app.tool(
        description=(
            "Log, search, or list project decisions. "
            "Actions: 'add' (log a decision), 'search' (find by keyword/fuzzy match), "
            "'list' (recent entries, default 20). "
            "For 'list', pass N via the decision param to override the default count, "
            "or pass a number via the context param to filter entries from the last N days."
        )
    )
    def proj_decision_log(
        action: str,
        decision: str = "",
        context: str = "",
        todo_id: str = "",
        tags: str = "",
        project_name: str | None = None,
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."

        if action == "add":
            if not decision:
                return "decision is required for 'add' action."
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            entry = storage.build_decision_entry(
                decision=decision,
                context=context,
                todo_id=todo_id,
                tags=tag_list,
            )
            storage.append_decision(cfg, name, entry)
            return f"Decision logged: {decision}"

        if action == "search":
            if not decision:
                return "decision param is required as the search query for 'search' action."
            entries = storage.load_decisions(cfg, name)
            if not entries:
                return "No decisions found."
            scored = [(score_entry(decision, e), e) for e in entries]
            matches = [(sc, e) for sc, e in scored if sc > _SEARCH_THRESHOLD]
            if not matches:
                return f"No decisions matching '{decision}'."
            matches.sort(key=lambda x: x[0], reverse=True)
            matches = matches[:10]
            lines = []
            for sc, e in matches:
                ts = str(e.get("timestamp", ""))
                dec = str(e.get("decision", ""))
                ctx = str(e.get("context", ""))
                tid = str(e.get("todo_id", ""))
                tgs = e.get("tags", [])
                parts = [f"[{ts}] {dec}  (score: {sc:.2f})"]
                if ctx:
                    parts.append(f"  context: {ctx}")
                if tid:
                    parts.append(f"  todo_id: {tid}")
                if isinstance(tgs, list):
                    parts.append(f"  tags: {', '.join(str(t) for t in tgs)}")
                lines.append("\n".join(parts))
            return "\n\n".join(lines)

        if action == "list":
            entries = storage.load_decisions(cfg, name)
            if not entries:
                return "No decisions found."
            # context param: filter by since_days (entries newer than N days ago)
            since_days: int | None = None
            if context:
                with contextlib.suppress(ValueError):
                    since_days = int(context)
            if since_days is not None:
                cutoff = datetime.now(UTC) - timedelta(days=since_days)
                cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
                recent = [e for e in entries if str(e.get("timestamp", "")) >= cutoff_str]
                recent.reverse()
            else:
                # decision param can override count
                count = 20
                if decision:
                    try:
                        count = int(decision)
                    except ValueError:
                        return f"Invalid count '{decision}'. Pass a number for the 'list' action."
                recent = entries[-count:]
                recent.reverse()
            lines = []
            for e in recent:
                ts = str(e.get("timestamp", ""))
                dec = str(e.get("decision", ""))
                ctx = str(e.get("context", ""))
                tid = str(e.get("todo_id", ""))
                tgs = e.get("tags", [])
                parts = [f"[{ts}] {dec}"]
                if ctx:
                    parts.append(f"  context: {ctx}")
                if tid:
                    parts.append(f"  todo_id: {tid}")
                if isinstance(tgs, list):
                    parts.append(f"  tags: {', '.join(str(t) for t in tgs)}")
                lines.append("\n".join(parts))
            return "\n\n".join(lines)

        return f"Unknown action '{action}'. Use 'add', 'search', or 'list'."
