"""Wiki link resolver: [[page]] and [[page#section]] → file path."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import anyio
import anyio.to_thread

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import storage

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP
else:
    from mcp.server.fastmcp import FastMCP  # noqa: TC002

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_link_resolve)


def _parse_link(link: str) -> tuple[str, str | None]:
    """Split wikilink notation into (slug, section).

    Handles all four forms:
        [[page]]                    → ("page", None)
        [[page#section]]            → ("page", "section")
        [[page|display alias]]      → ("page", None)         — alias dropped
        [[page#section|display]]    → ("page", "section")    — alias dropped

    The display alias after `|` is only for human-readable rendering at the
    call site; the resolver uses slug+section to find the file.
    """
    link = link.strip().strip("[]").strip()
    # Strip display alias first (`|` always comes after slug+section)
    if "|" in link:
        link = link.split("|", 1)[0].strip()
    if "#" in link:
        slug, section = link.split("#", 1)
        return slug.strip(), section.strip()
    return link, None


def _find_page(pages_root: Path, slug: str) -> tuple[Path | None, list[str]]:
    """Find a page by slug (case-insensitive) or alias. Returns (path, collision-candidates)."""
    slug_lower = slug.lower()
    candidates: list[Path] = []
    for md in sorted(pages_root.rglob("*.md")):
        if md.stem.lower() == slug_lower:
            candidates.append(md)
            continue
        try:
            fm, _ = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        aliases: list[Any] = fm.get("aliases", []) or []
        if any(str(a).lower() == slug_lower for a in aliases):
            candidates.append(md)
    if not candidates:
        return None, []
    return candidates[0], [str(c) for c in candidates[1:]]


def _section_in_body(body: str, section: str) -> bool:
    section_lower = section.strip().lower()
    return any(m.group(1).strip().lower() == section_lower for m in _HEADING_RE.finditer(body))


async def wiki_link_resolve(link: str) -> str:
    """Resolve a [[page]] or [[page#section]] link to file path + section flag."""
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir

    def _do_resolve() -> dict[str, Any]:
        pages_root = storage.pages_dir(wiki_dir)
        slug, section = _parse_link(link)
        if not pages_root.exists():
            return {"resolved": None, "section_found": None, "candidates": []}

        path, candidates = _find_page(pages_root, slug)
        if path is None:
            return {"resolved": None, "section_found": None, "candidates": candidates}

        section_found: bool | None = None
        if section is not None:
            try:
                _, body = fm_mod.parse(path.read_text())
                section_found = _section_in_body(body, section)
            except fm_mod.FrontmatterError:
                section_found = False

        return {
            "resolved": str(path),
            "section_found": section_found,
            "candidates": candidates,
        }

    return json.dumps(await anyio.to_thread.run_sync(_do_resolve))
