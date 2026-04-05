"""MCP tool for project decision logging."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    """Register proj_decision_log tool with the MCP app."""

    @app.tool(
        description=(
            "Log, search, or list project decisions. "
            "Actions: 'add' (log a decision), 'search' (find by keyword/regex), "
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
            try:
                pattern = re.compile(decision, re.IGNORECASE)
            except re.error:
                pattern = re.compile(re.escape(decision), re.IGNORECASE)
            matches = [
                e
                for e in entries
                if pattern.search(str(e.get("decision", ""))) or pattern.search(str(e.get("context", "")))
            ]
            if not matches:
                return f"No decisions matching '{decision}'."
            matches = matches[:10]
            lines = []
            for e in matches:
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

        if action == "list":
            entries = storage.load_decisions(cfg, name)
            if not entries:
                return "No decisions found."
            # context param: filter by since_days (entries newer than N days ago)
            since_days: int | None = None
            if context:
                try:
                    since_days = int(context)
                except ValueError:
                    pass
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
