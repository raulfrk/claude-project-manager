"""Tier-1 lint MCP tools (pure-data, no LLM).

Each tool returns JSON-serializable findings. Tier-2 semantic checks live in
skill prompts (Phase 4), not here.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import yaml

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import profile as profile_mod
from server.lib import storage

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP
else:
    from mcp.server.fastmcp import FastMCP  # noqa: TC002


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)
    mcp.tool()(wiki_lint_broken_links)
    mcp.tool()(wiki_lint_broken_section_refs)
    mcp.tool()(wiki_lint_category_violations)


_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _collect_link_targets(fm: dict[str, Any], body: str) -> list[str]:
    """Return all link refs from both frontmatter.links_to and inline [[page]] in body."""
    targets: list[str] = []
    links_to: list[Any] = fm.get("links_to", []) or []  # type: ignore[assignment]
    for t in links_to:
        targets.append(str(t))
    for m in _WIKILINK_RE.finditer(body):
        targets.append(m.group(1).strip().strip("[]").strip())
    return targets


def _find_page_by_slug_or_alias(wiki_dir: Path, slug: str) -> Path | None:
    """Return path of page matching slug (case-insensitive) or any alias."""
    slug_lower = slug.lower()
    pages_root = storage.pages_dir(wiki_dir)
    if not pages_root.exists():
        return None
    for md in pages_root.rglob("*.md"):
        if md.stem.lower() == slug_lower:
            return md
        try:
            fm, _ = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        aliases: list[Any] = fm.get("aliases", []) or []  # type: ignore[assignment]
        if any(str(a).lower() == slug_lower for a in aliases):
            return md
    return None


def _section_present(body: str, section: str) -> bool:
    """Check if heading with given section name (case-insensitive) exists in body."""
    section_lower = section.strip().lower()
    return any(m.group(1).strip().lower() == section_lower for m in _HEADING_RE.finditer(body))


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


def wiki_lint_broken_links() -> str:
    """Refs from pages' links_to + inline [[wikilinks]] whose target page doesn't exist.

    For `[[page#section]]`, only reports when the PAGE is missing; missing sections
    are reported by wiki_lint_broken_section_refs.

    Returns JSON {broken: [{from, link}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    broken: list[dict[str, str]] = []
    for md, fm, body in _iter_pages(wiki_dir):
        slug = md.stem
        for target in _collect_link_targets(fm, body):
            page_part = target.split("#", 1)[0].strip()
            if not page_part:
                continue
            resolved = _find_page_by_slug_or_alias(wiki_dir, page_part)
            if resolved is None:
                broken.append({"from": slug, "link": target})
    return json.dumps({"broken": broken})


def wiki_lint_broken_section_refs() -> str:
    """Refs like [[page#section]] where page resolves but section heading doesn't.

    Returns JSON {broken: [{from, link, resolved_page}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    broken: list[dict[str, str]] = []
    for md, fm, body in _iter_pages(wiki_dir):
        slug = md.stem
        for target in _collect_link_targets(fm, body):
            if "#" not in target:
                continue
            page_part, section = target.split("#", 1)
            resolved = _find_page_by_slug_or_alias(wiki_dir, page_part.strip())
            if resolved is None:
                # Page missing — falls to broken_links, not here
                continue
            try:
                _, target_body = fm_mod.parse(resolved.read_text())
            except fm_mod.FrontmatterError:
                continue
            if not _section_present(target_body, section.strip()):
                broken.append(
                    {
                        "from": slug,
                        "link": target,
                        "resolved_page": str(resolved),
                    }
                )
    return json.dumps({"broken": broken})


def wiki_lint_category_violations() -> str:
    """Pages whose dir is not in active profile's configured categories.

    Flat-layout pages (no category dir) under non-minimal profile also flagged w/
    found_category=None. Minimal profile (empty categories) → no violations.
    Missing profile config → skip (returns []).

    Returns JSON {violations: [{page, found_category, configured, path}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    try:
        profile = profile_mod.load_profile(wiki_dir)
    except profile_mod.ProfileError:
        return json.dumps({"violations": []})

    # Minimal profile explicitly allows anything — skip check.
    if not profile.categories:
        return json.dumps({"violations": []})

    configured = sorted(profile.categories)
    configured_set = set(profile.categories)
    pages_root = storage.pages_dir(wiki_dir)
    violations: list[dict[str, Any]] = []
    for md, _fm, _body in _iter_pages(wiki_dir):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else None
        if cat is None or cat not in configured_set:
            violations.append(
                {
                    "page": md.stem,
                    "found_category": cat,
                    "configured": configured,
                    "path": str(md),
                }
            )
    return json.dumps({"violations": violations})
