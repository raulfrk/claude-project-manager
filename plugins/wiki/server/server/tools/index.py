"""Wiki index.md tools: read + rebuild."""

from __future__ import annotations

import json
import re
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

import anyio
import anyio.to_thread

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import profile as profile_mod
from server.lib import storage
from server.lib.storage import WikiLockTimeoutError

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
else:
    # At runtime, for FastMCP usage in register()
    from mcp.server.fastmcp import FastMCP  # noqa: TC002

INDEX_FILENAME = "index.md"
RECENT_LIMIT = 10

_CATEGORY_HEADER_RE = re.compile(r"^## (\S.+?) \((\d+)\)$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
    """Register wiki index tools."""
    mcp.tool()(wiki_index_read)
    mcp.tool()(wiki_index_rebuild)


def _first_summary_line(body: str) -> str:
    """Extract a one-line summary from a page body (first non-empty non-heading line)."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        return stripped[:200]
    return ""


def _build_index_text(wiki_dir: Path) -> tuple[str, dict[str, int], int]:
    """Sync helper: walk pages, build index.md text, return (text, counts, recent_count)."""
    try:
        profile = profile_mod.load_profile(wiki_dir)
    except profile_mod.ProfileError:
        profile = None

    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        pages_root.mkdir(parents=True, exist_ok=True)

    by_category: dict[str, list[dict[str, Any]]] = {}
    all_pages: list[dict[str, Any]] = []
    for md in sorted(pages_root.rglob("*.md")):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else "uncategorized"
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        entry = {
            "slug": md.stem,
            "title": fm.get("title", md.stem),
            "summary": _first_summary_line(body),
            "last_ingested": fm.get("last_ingested", ""),
        }
        by_category.setdefault(cat, []).append(entry)
        all_pages.append(entry)

    recent_sorted = sorted(all_pages, key=lambda e: str(e["last_ingested"]), reverse=True)[
        :RECENT_LIMIT
    ]

    # Order categories by profile; unknown categories appended at end alphabetically
    category_order: list[str] = []
    if profile and profile.categories:
        category_order = [c for c in profile.categories if c in by_category]
        extras = sorted(set(by_category.keys()) - set(profile.categories))
        category_order.extend(extras)
    else:
        category_order = sorted(by_category.keys())

    lines: list[str] = ["# Wiki Index", ""]
    for cat in category_order:
        entries = by_category[cat]
        lines.append(f"## {cat.title()} ({len(entries)})")
        for e in sorted(entries, key=lambda x: str(x["title"])):
            summary = f" — {e['summary']}" if e["summary"] else ""
            lines.append(f"- [[{e['slug']}]]{summary}")
        lines.append("")

    if recent_sorted:
        lines.append(f"## Recent (by last_ingested, top {RECENT_LIMIT})")
        for e in recent_sorted:
            date_part = str(e["last_ingested"]).split("T")[0]
            lines.append(f"- [[{e['slug']}]] ({date_part})")
        lines.append("")

    counts = {c: len(v) for c, v in by_category.items()}
    return "\n".join(lines), counts, len(recent_sorted)


async def wiki_index_rebuild() -> str:
    """Regenerate index.md by scanning pages/**. Groups by active profile categories."""
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    try:
        # Heavy: walk pages, read frontmatter, sort, render. Worker thread.
        rendered_text, counts, recent_count = await anyio.to_thread.run_sync(
            _build_index_text, wiki_dir
        )
        async with storage.wiki_lock(wiki_dir):
            await anyio.to_thread.run_sync(
                storage.atomic_write, wiki_dir / INDEX_FILENAME, rendered_text
            )
        return json.dumps(
            {
                "entries_by_category": counts,
                "recent_count": recent_count,
            }
        )
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})


async def wiki_index_read() -> str:
    """Read index.md + return content + parsed category counts + recent list."""
    cfg = config_mod.load_config()
    index_path: Path = cfg.wiki_dir / INDEX_FILENAME

    def _do_read() -> dict[str, Any]:
        if not index_path.exists():
            return {"content": "", "categories": {}, "recent": []}
        content = index_path.read_text()
        categories: dict[str, int] = {}
        for m in _CATEGORY_HEADER_RE.finditer(content):
            name = m.group(1).strip().lower()
            if name.startswith("recent"):
                continue
            categories[name] = int(m.group(2))

        # Parse "## Recent ..." section for slug list
        recent: list[str] = []
        if "## Recent" in content:
            section = content.split("## Recent", 1)[1]
            for line in section.splitlines():
                m = re.match(r"- \[\[(.+?)\]\]", line.strip())
                if m:
                    recent.append(m.group(1))
        return {"content": content, "categories": categories, "recent": recent}

    result = await anyio.to_thread.run_sync(_do_read)
    return json.dumps(result)
