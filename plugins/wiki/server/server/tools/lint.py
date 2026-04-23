"""Tier-1 lint MCP tools (pure-data, no LLM).

Each tool returns JSON-serializable findings. Tier-2 semantic checks live in
skill prompts (Phase 4), not here.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import storage

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP
else:
    from mcp.server.fastmcp import FastMCP  # noqa: TC002


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)


def _load_lint_config(wiki_dir: Path) -> dict[str, Any]:
    """Load wiki/config.yaml's lint section. Returns defaults if missing."""
    cfg_path = wiki_dir / "config.yaml"
    defaults: dict[str, Any] = {
        "stale_after_days": 90,
        "orphan_min_page_count": 3,
    }
    if not cfg_path.exists():
        return defaults
    try:
        data = yaml.safe_load(cfg_path.read_text())
        if data is None:
            return defaults
        if not isinstance(data, dict):
            return defaults
    except yaml.YAMLError:
        return defaults
    lint_section: dict[str, Any] = data.get("lint", {}) or {}  # type: ignore[assignment]
    merged = {**defaults, **lint_section}
    return merged


def _iter_pages(wiki_dir: Path) -> Any:  # Generator[tuple[Path, dict[str, Any], str], None, None]
    """Yield (path, frontmatter, body) for every parseable page under pages/."""
    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        return
    for md in sorted(pages_root.rglob("*.md")):
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        yield md, fm, body


def wiki_lint_orphans() -> str:
    """Pages with 0 inbound + 0 outbound links_to refs.

    Skipped when total page count < lint.orphan_min_page_count (default 3).
    Returns JSON {orphans: [{slug, category, path}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    lint_cfg = _load_lint_config(wiki_dir)
    min_pages = int(lint_cfg.get("orphan_min_page_count", 3))

    pages: list[tuple[Path, dict[str, Any], str]] = list(_iter_pages(wiki_dir))
    if len(pages) < min_pages:
        return json.dumps({"orphans": []})

    inbound: dict[str, int] = {}
    for _, fm, _ in pages:
        links_to: list[Any] = fm.get("links_to", []) or []  # type: ignore[assignment]
        for target in links_to:
            inbound[str(target)] = inbound.get(str(target), 0) + 1

    pages_root = storage.pages_dir(wiki_dir)
    orphans: list[dict[str, Any]] = []
    for md, fm, _ in pages:
        slug = md.stem
        outlinks: list[Any] = fm.get("links_to", []) or []  # type: ignore[assignment]
        if not outlinks and inbound.get(slug, 0) == 0:
            rel = md.relative_to(pages_root)
            cat = rel.parts[0] if len(rel.parts) > 1 else None
            orphans.append({"slug": slug, "category": cat, "path": str(md)})
    return json.dumps({"orphans": orphans})
