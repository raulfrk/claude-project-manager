"""MCP tool for searching project knowledge stores."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools.config import require_config
from server.tools.decisions import score_entry

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP

    from server.lib.models import ProjConfig

_VALID_SCOPES = ("all", "sessions", "notes", "requirements", "research", "decisions")
_MAX_SNIPPETS = 5
_CONTEXT_LINES = 3
_DECISIONS_THRESHOLD = 0.5


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

    # decisions are handled separately via structured fuzzy search
    # so we do NOT add them to the raw file list here

    return files


def _extract_snippets(
    file_path: Path, query: str, tracking_root: Path
) -> list[dict[str, str | int | float]]:
    """Search a file for query matches and extract context snippets."""
    try:
        text = file_path.read_text()
    except OSError:
        return []

    lines = text.splitlines()
    matches: list[dict[str, str | int | float]] = []

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
            matches.append(
                {
                    "source": str(rel),
                    "match": line.strip(),
                    "context": context_block,
                }
            )

    return matches


def _search_decisions_fuzzy(
    cfg: ProjConfig, name: str, query: str, tracking_root: Path
) -> list[dict[str, str | int | float]]:
    """Search the decision log using structured fuzzy scoring."""
    entries = storage.load_decisions(cfg, name)
    if not entries:
        return []

    scored = [(score_entry(query, e), e) for e in entries]
    matches = [(sc, e) for sc, e in scored if sc > _DECISIONS_THRESHOLD]
    matches.sort(key=lambda x: x[0], reverse=True)

    results: list[dict[str, str | int | float]] = []
    dp = storage.decisions_path(cfg, name)
    try:
        rel = str(dp.relative_to(tracking_root))
    except ValueError:
        rel = str(dp)

    for sc, e in matches:
        dec = str(e.get("decision", ""))
        ctx = str(e.get("context", ""))
        tags = e.get("tags", [])
        tags_str = ", ".join(str(t) for t in tags) if isinstance(tags, list) else ""
        context_block = dec
        if ctx:
            context_block += f"\n  context: {ctx}"
        if tags_str:
            context_block += f"\n  tags: {tags_str}"
        results.append(
            {
                "source": rel,
                "match": dec,
                "context": context_block,
                "score": round(sc, 3),
            }
        )

    return results


def register(app: FastMCP) -> None:
    """Register proj_search_knowledge tool with the MCP app."""

    @app.tool(
        description=(
            "Search across project knowledge stores (sessions, notes, requirements, "
            "research, decisions). Returns up to 5 snippets with surrounding context, "
            "sorted by match density. Decisions are searched with fuzzy token matching."
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

        all_snippets: list[dict[str, str | int | float]] = []
        for fp in files:
            all_snippets.extend(_extract_snippets(fp, query, tracking_root))

        # Decisions: use structured fuzzy search instead of raw file regex
        if scope in ("all", "decisions"):
            all_snippets.extend(_search_decisions_fuzzy(cfg, name, query, tracking_root))

        total_matches = len(all_snippets)

        # Sort by score field if present, else by regex match density
        def _sort_key(snippet: dict[str, str | int | float]) -> float:
            if "score" in snippet:
                return float(snippet["score"])
            ctx = str(snippet.get("context", ""))
            return float(len(re.findall(query, ctx, re.IGNORECASE)))

        all_snippets.sort(key=_sort_key, reverse=True)
        top = all_snippets[:_MAX_SNIPPETS]

        return json.dumps({"snippets": top, "total_matches": total_matches}, indent=2)
