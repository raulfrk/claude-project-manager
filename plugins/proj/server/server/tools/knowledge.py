"""MCP tool for searching project knowledge stores."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.models import ProjConfig
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_VALID_SCOPES = ("all", "sessions", "notes", "requirements", "research", "decisions")
_MAX_SNIPPETS = 5
_CONTEXT_LINES = 3


def _resolve_files(cfg: ProjConfig, name: str, scope: str) -> list[Path]:
    """Return the list of files to search for the given scope."""
    files: list[Path] = []
    t_dir = storage.tracking_dir(cfg, name)

    if scope in ("all", "sessions"):
        s_dir = storage.sessions_dir(cfg, name)
        if s_dir.is_dir():
            files.extend(sorted(s_dir.glob("session-*.md")))

    if scope in ("all", "notes"):
        np = storage.notes_path(cfg, name)
        if np.exists():
            files.append(np)

    if scope in ("all", "requirements"):
        todos_dir = t_dir / "todos"
        if todos_dir.is_dir():
            files.extend(sorted(todos_dir.glob("*/requirements.md")))

    if scope in ("all", "research"):
        todos_dir = t_dir / "todos"
        if todos_dir.is_dir():
            files.extend(sorted(todos_dir.glob("*/research.md")))

    if scope in ("all", "decisions"):
        dp = storage.decisions_path(cfg, name)
        if dp.exists():
            files.append(dp)

    return files


def _extract_snippets(
    file_path: Path, query: str, tracking_root: Path
) -> list[dict[str, str | int]]:
    """Search a file for query matches and extract context snippets."""
    try:
        text = file_path.read_text()
    except OSError:
        return []

    lines = text.splitlines()
    matches: list[dict[str, str | int]] = []

    for i, line in enumerate(lines):
        if re.search(query, line, re.IGNORECASE):
            start = max(0, i - _CONTEXT_LINES)
            end = min(len(lines), i + _CONTEXT_LINES + 1)
            context_block = "\n".join(lines[start:end])
            # Relative path from tracking root for cleaner display
            try:
                rel = file_path.relative_to(tracking_root)
            except ValueError:
                rel = file_path
            matches.append({
                "source": str(rel),
                "match": line.strip(),
                "context": context_block,
            })

    return matches


def register(app: FastMCP) -> None:
    """Register proj_search_knowledge tool with the MCP app."""

    @app.tool(
        description=(
            "Search across project knowledge stores (sessions, notes, requirements, "
            "research, decisions). Returns up to 5 snippets with surrounding context, "
            "sorted by match density."
        )
    )
    def proj_search_knowledge(
        query: str, scope: str = "all", project_name: str | None = None
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."

        if scope not in _VALID_SCOPES:
            return f"Invalid scope '{scope}'. Must be one of: {', '.join(_VALID_SCOPES)}"

        tracking_root = storage.tracking_dir(cfg, name)
        files = _resolve_files(cfg, name, scope)

        all_snippets: list[dict[str, str | int]] = []
        for fp in files:
            all_snippets.extend(_extract_snippets(fp, query, tracking_root))

        total_matches = len(all_snippets)

        # Sort by match density: count how many times the query matches in the context
        def _density(snippet: dict[str, str | int]) -> int:
            ctx = str(snippet.get("context", ""))
            return len(re.findall(query, ctx, re.IGNORECASE))

        all_snippets.sort(key=_density, reverse=True)
        top = all_snippets[:_MAX_SNIPPETS]

        return json.dumps({"snippets": top, "total_matches": total_matches}, indent=2)
