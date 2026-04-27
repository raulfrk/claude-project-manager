"""MCP tool: filter a session file before wiki ingest dispatch.

See spec docs/superpowers/specs/2026-04-26-wiki-ingest-todo-filter-design.md.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib.wiki_ingest_filter import filter_session_text

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register(app: FastMCP) -> None:
    """Register wiki_ingest_filter_session tool."""

    @app.tool(
        description=(
            "Filter a session file for wiki ingest by stripping todo-tracked "
            "content (todo IDs, status framing, '## Todos Worked On' section). "
            "Writes filtered output to /tmp/wiki-ingest-<uuid4>.md and returns "
            "the tmp path. Caller is responsible for deleting the tmp file "
            "after the wiki ingest subagent returns."
        )
    )
    def wiki_ingest_filter_session(session_path: str) -> str:
        src = Path(session_path)
        if not src.is_file():
            return json.dumps(
                {"status": "error", "error": f"Session file not found: {session_path}"}
            )
        try:
            text = src.read_text(encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to read session file: %s", session_path)
            return json.dumps({"status": "error", "error": f"Read failed: {exc}"})

        filtered = filter_session_text(text)
        # Path documented in spec; consumer (/proj:save) deletes after ingest subagent returns.
        from hook_transport.socket_path import tmp_dir

        tmp_path = tmp_dir() / f"wiki-ingest-{uuid.uuid4()}.md"
        try:
            tmp_path.write_text(filtered, encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to write tmp file: %s", tmp_path)
            return json.dumps({"status": "error", "error": f"Write failed: {exc}"})

        return json.dumps(
            {
                "status": "filtered",
                "tmp_path": str(tmp_path),
                "original_bytes": len(text.encode("utf-8")),
                "filtered_bytes": len(filtered.encode("utf-8")),
            }
        )
