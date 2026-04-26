"""Wiki append-only log (log.md) tools."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import TYPE_CHECKING, Any

import anyio
import anyio.to_thread

from server.lib import config as config_mod
from server.lib import storage
from server.lib.storage import WikiLockTimeoutError

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP
else:
    # At runtime, for FastMCP usage in register()
    from mcp.server.fastmcp import FastMCP  # noqa: TC002

LOG_FILENAME = "log.md"
_ENTRY_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] (\S+) \| (.+)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_log_append)
    mcp.tool()(wiki_log_read)


def _do_log_write(wiki_dir: Path, log_path: Path, entry: str) -> None:
    """Sync helper: filesystem ops on a worker thread."""
    wiki_dir.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text() if log_path.exists() else ""
    storage.atomic_write(log_path, existing + entry)


async def wiki_log_append(action: str, title: str, body: str = "") -> str:
    """Append an entry to log.md.

    Format: `## [YYYY-MM-DD] <action> | <title>` followed by optional body + blank line.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    log_path = wiki_dir / LOG_FILENAME
    today = date.today().isoformat()
    header = f"## [{today}] {action} | {title}\n"
    entry = header + (body + "\n" if body else "") + "\n"
    try:
        async with storage.wiki_lock(wiki_dir):
            await anyio.to_thread.run_sync(_do_log_write, wiki_dir, log_path, entry)
        return json.dumps({"entry": entry.strip(), "path": str(log_path)})
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})


async def wiki_log_read(
    since: str | None = None,
    action_filter: str | None = None,
    limit: int = 0,
) -> str:
    """Read log entries, optionally filtered.

    Args:
        since: ISO date string (YYYY-MM-DD); include entries with date >= since.
        action_filter: include only entries with matching action.
        limit: 0 = unlimited; otherwise return most-recent N matching.
    """
    cfg = config_mod.load_config()
    log_path = cfg.wiki_dir / LOG_FILENAME

    def _do_read() -> dict[str, Any]:
        if not log_path.exists():
            return {"entries": []}
        content = log_path.read_text()
        entries: list[dict[str, Any]] = []
        matches = list(_ENTRY_RE.finditer(content))
        for i, m in enumerate(matches):
            entry_date, action, title = m.group(1), m.group(2), m.group(3)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body_text = content[start:end].strip()
            if since and entry_date < since:
                continue
            if action_filter and action != action_filter:
                continue
            entries.append(
                {"date": entry_date, "action": action, "title": title, "body": body_text}
            )
        if limit > 0 and len(entries) > limit:
            entries = entries[-limit:]
        return {"entries": entries}

    result = await anyio.to_thread.run_sync(_do_read)
    return json.dumps(result)
