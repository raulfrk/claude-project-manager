"""Tier-1 lint MCP tools (pure-data, no LLM).

Each tool returns JSON-serializable findings. Tier-2 semantic checks live in
skill prompts (Phase 4), not here.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
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


_DEFAULT_REQUIRED_FIELDS = ("title", "tags", "links_to", "scope", "sources", "last_ingested")


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_lint_orphans)
    mcp.tool()(wiki_lint_broken_links)
    mcp.tool()(wiki_lint_broken_section_refs)
    mcp.tool()(wiki_lint_category_violations)
    mcp.tool()(wiki_lint_stale)
    mcp.tool()(wiki_lint_schema)
    mcp.tool()(wiki_lint_duplicates)


_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _parse_iso_utc(value: str) -> datetime | None:
    """Best-effort parse of an ISO-8601 UTC datetime string. Returns None on failure."""
    if not value:
        return None
    # datetime.fromisoformat on Py 3.11+ accepts trailing 'Z'; be defensive for older runs.
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


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


def wiki_lint_stale(days: int = 0) -> str:
    """Pages whose last_ingested is older than `days` (or lint.stale_after_days default).

    Pages with unparseable last_ingested are NOT flagged here — they're caught
    by wiki_lint_schema.

    Returns JSON {stale: [{slug, path, last_ingested, age_days}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    lint_cfg = _load_lint_config(wiki_dir)
    threshold_days = int(days) if days > 0 else int(lint_cfg.get("stale_after_days", 90))
    cutoff = datetime.now(UTC) - timedelta(days=threshold_days)
    stale: list[dict[str, Any]] = []
    for md, fm, _ in _iter_pages(wiki_dir):
        last_ingested = str(fm.get("last_ingested", "") or "")
        parsed = _parse_iso_utc(last_ingested)
        if parsed is None:
            continue
        if parsed < cutoff:
            age_days = (datetime.now(UTC) - parsed).days
            stale.append(
                {
                    "slug": md.stem,
                    "path": str(md),
                    "last_ingested": last_ingested,
                    "age_days": age_days,
                }
            )
    return json.dumps({"stale": stale})


def _load_required_fields(wiki_dir: Path) -> list[str]:
    """Load required_frontmatter list from wiki/config.yaml. Returns defaults if absent."""
    cfg_path = wiki_dir / "config.yaml"
    if not cfg_path.exists():
        return list(_DEFAULT_REQUIRED_FIELDS)
    try:
        raw_data = yaml.safe_load(cfg_path.read_text())
        if raw_data is None:
            return list(_DEFAULT_REQUIRED_FIELDS)
        if not isinstance(raw_data, dict):
            return list(_DEFAULT_REQUIRED_FIELDS)
    except yaml.YAMLError:
        return list(_DEFAULT_REQUIRED_FIELDS)
    data: dict[str, Any] = raw_data  # type: ignore[assignment]
    required: list[Any] = data.get("required_frontmatter", []) or []  # type: ignore[assignment]
    return [str(f) for f in required]


def wiki_lint_schema() -> str:
    """Pages violating required_frontmatter.

    A page violates schema when: (a) any required field is absent, OR (b) the
    last_ingested value is not a parseable ISO-8601 datetime.

    Returns JSON {violations: [{page, path, missing_fields, invalid_fields}]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    required = _load_required_fields(wiki_dir)
    violations: list[dict[str, Any]] = []
    for md, fm, _ in _iter_pages(wiki_dir):
        missing = [f for f in required if f not in fm]
        invalid: list[str] = []
        if "last_ingested" in fm:
            li = str(fm.get("last_ingested", "") or "")
            if li and _parse_iso_utc(li) is None:
                invalid.append("last_ingested")
        if missing or invalid:
            violations.append(
                {
                    "page": md.stem,
                    "path": str(md),
                    "missing_fields": missing,
                    "invalid_fields": invalid,
                }
            )
    return json.dumps({"violations": violations})


# SYNC CONTRACT (todos 730 + Batch A validation):
# The functions below are the canonical reference impl of the section-map drift
# algorithm. The PRODUCTION drift check at /wiki:lint runtime is performed by
# the LLM subagent dispatched per `plugins/wiki/skills/lint/references/tier2-section-map-drift.md`,
# which re-implements the same algorithm in prose. Tests pin THIS impl; nothing
# pins the prose. If you change the algorithm here (anchor regex, sentinel
# semantics, output kinds), you MUST also update the prose in the reference doc
# above — and vice versa. Two sources of truth = drift over time.
#
# Why we keep both: the Python is testable + machine-checkable; the prose is
# what the runtime LLM actually executes. Promoting one to the other is a
# larger refactor (todo 736 follow-up — investigate parallel-orchestration
# quality recipe).
_TEMPLATE_START_RE = re.compile(r"<!--\s*session-template-start\s*-->")
_TEMPLATE_END_RE = re.compile(r"<!--\s*session-template-end\s*-->")
_TEMPLATE_H2_RE = re.compile(r"^## (.+)$")


def _extract_save_skill_h2s(skill_text: str) -> list[str] | None:
    """Extract H2 headings from /proj:save SKILL.md step-7 session template.

    Anchors on HTML comment markers <!-- session-template-start --> and
    <!-- session-template-end --> wrapping the fenced template block.
    Lines inside the block may be indented (e.g. 3 spaces) — each line is stripped
    before matching so both indented + flush formats are supported.

    Returns:
        None  — anchor or fence not found (parse failure / malformed SKILL)
        []    — anchor + fence found but template contains zero H2s (legit-empty)
        [...]  — list of whitespace-trimmed H2 heading names
    """
    start_match = _TEMPLATE_START_RE.search(skill_text)
    if not start_match:
        return None
    after_start = skill_text[start_match.end() :]
    # Find opening ``` fence after the start marker
    open_fence = after_start.find("```")
    if open_fence == -1:
        return None
    block_start = open_fence + 3
    # Find closing ``` after the opening fence
    close_fence = after_start.find("```", block_start)
    if close_fence == -1:
        return None
    block = after_start[block_start:close_fence]
    headings: list[str] = []
    for line in block.splitlines():
        m = _TEMPLATE_H2_RE.match(line.strip())
        if m:
            headings.append(m.group(1).strip())
    return headings


def check_section_map_drift(
    skill_path: Path | None,
    section_map: dict[str, str],
) -> list[dict[str, str]]:
    """Detect drift between wiki.yaml section_map keys and /proj:save template H2s.

    Returns list of warning dicts with keys: kind, value, message.
    kind is "missing_from_template", "missing_from_config", "skill_not_found",
    or "template_unparseable".

    If skill_path is None or doesn't exist → returns single not-found warning.
    If SKILL exists but anchor/fence not found → returns single template_unparseable warning.
    """
    if skill_path is None or not skill_path.exists():
        return [
            {
                "kind": "skill_not_found",
                "value": "",
                "message": "WARN: Could not locate /proj:save SKILL.md for drift check",
            }
        ]

    skill_text = skill_path.read_text()
    template_h2s = _extract_save_skill_h2s(skill_text)

    if template_h2s is None:
        return [
            {
                "kind": "template_unparseable",
                "value": str(skill_path),
                "message": (
                    "WARN: /proj:save SKILL.md found but session-template markers or fence not"
                    " found — skipping drift check"
                ),
            }
        ]

    section_map_keys = list(section_map.keys())

    warnings: list[dict[str, str]] = []
    for key in section_map_keys:
        if key not in template_h2s:
            warnings.append(
                {
                    "kind": "missing_from_template",
                    "value": key,
                    "message": (
                        f"WARN: section_map key '{key}' has no matching H2 in /proj:save template"
                    ),
                }
            )
    for h2 in template_h2s:
        if h2 not in section_map_keys:
            warnings.append(
                {
                    "kind": "missing_from_config",
                    "value": h2,
                    "message": f"WARN: /proj:save H2 '{h2}' has no section_map entry",
                }
            )
    return warnings


def wiki_lint_duplicates() -> str:
    """Pages whose filename stem (slug) collides (case-insensitive) across the wiki.

    Returns JSON {duplicates: [[path_a, path_b, ...], ...]}.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    by_slug: dict[str, list[str]] = {}
    for md, _fm, _body in _iter_pages(wiki_dir):
        key = md.stem.lower()
        by_slug.setdefault(key, []).append(str(md))
    duplicates = [sorted(paths) for paths in by_slug.values() if len(paths) > 1]
    return json.dumps({"duplicates": duplicates})
