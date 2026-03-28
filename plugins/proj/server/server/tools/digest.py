"""MCP tool for session digest — aggregate decisions, questions, and insights."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Section heading → JSON key mapping
_SECTION_MAP: dict[str, str] = {
    "Key Decisions": "decisions",
    "Open Questions": "questions",
    "Insights Discovered": "insights",
}

_VALID_FOCUS = {"decisions", "questions", "insights", "all"}


def _parse_session(content: str) -> dict[str, list[str]]:
    """Parse a session markdown file into categorised bullet lists."""
    result: dict[str, list[str]] = {v: [] for v in _SECTION_MAP.values()}
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    for section in sections:
        for heading, key in _SECTION_MAP.items():
            if section.startswith(f"## {heading}"):
                for line in section.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        result[key].append(stripped[2:])
                break
    return result


def _deduplicate(items: list[str]) -> list[str]:
    """Remove exact duplicates while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def register(app: FastMCP) -> None:
    """Register proj_session_digest tool with the MCP app."""

    @app.tool(
        description=(
            "Aggregate key decisions, open questions, and insights from recent session files. "
            "Returns deduplicated bullet points across the last N sessions. "
            "Use focus='decisions'|'questions'|'insights' to filter, or 'all' for everything."
        )
    )
    def proj_session_digest(
        last_n: int = 3,
        focus: str = "all",
        project_name: str | None = None,
    ) -> str:
        if focus not in _VALID_FOCUS:
            return f"Invalid focus '{focus}'. Must be one of: {', '.join(sorted(_VALID_FOCUS))}."

        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."

        sess_dir = storage.sessions_dir(cfg, name)
        if not sess_dir.is_dir():
            return json.dumps(
                {"focus": focus, "sessions_read": 0, "decisions": [], "questions": [], "insights": []},
                indent=2,
            )

        files = sorted(sess_dir.glob("session-*.md"))
        selected = files[-last_n:] if last_n < len(files) else files

        aggregated: dict[str, list[str]] = {"decisions": [], "questions": [], "insights": []}
        for path in selected:
            parsed = _parse_session(path.read_text())
            for key in aggregated:
                aggregated[key].extend(parsed[key])

        # Deduplicate each category
        for key in aggregated:
            aggregated[key] = _deduplicate(aggregated[key])

        # Filter by focus
        if focus != "all":
            result_data = {
                "focus": focus,
                "sessions_read": len(selected),
                focus: aggregated[focus],
            }
        else:
            result_data = {
                "focus": focus,
                "sessions_read": len(selected),
                **aggregated,
            }

        return json.dumps(result_data, indent=2)
