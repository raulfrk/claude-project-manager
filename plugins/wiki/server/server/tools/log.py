"""Wiki append-only log (log.md) tools."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from server.lib import config as config_mod
from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
else:
    # At runtime, for FastMCP usage in register()
    from mcp.server.fastmcp import FastMCP  # noqa: TC002

LOG_FILENAME = "log.md"
_ENTRY_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] (\S+) \| (.+)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_log_append)
    mcp.tool()(wiki_log_read)


def wiki_log_append(action: str, title: str, body: str = "") -> str:
    """Append an entry to log.md.

    Format: `## [YYYY-MM-DD] <action> | <title>` followed by optional body + blank line.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    log_path = wiki_dir / LOG_FILENAME
    today = date.today().isoformat()
    header = f"## [{today}] {action} | {title}\n"
    entry = header + (body + "\n" if body else "") + "\n"

    with storage.wiki_lock(wiki_dir):
        wiki_dir.mkdir(parents=True, exist_ok=True)
        existing = log_path.read_text() if log_path.exists() else ""
        storage.atomic_write(log_path, existing + entry)

    return json.dumps({"entry": entry.strip(), "path": str(log_path)})


def wiki_log_read(
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
    if not log_path.exists():
        return json.dumps({"entries": []})

    content = log_path.read_text()
    entries: list[dict[str, Any]] = []

    # Find each entry header; body is text between this header and next (or EOF).
    matches = list(_ENTRY_RE.finditer(content))
    for i, m in enumerate(matches):
        entry_date, action, title = m.group(1), m.group(2), m.group(3)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if since and entry_date < since:
            continue
        if action_filter and action != action_filter:
            continue
        entries.append({"date": entry_date, "action": action, "title": title, "body": body})

    if limit > 0 and len(entries) > limit:
        entries = entries[-limit:]

    return json.dumps({"entries": entries})
