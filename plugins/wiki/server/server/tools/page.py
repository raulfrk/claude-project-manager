"""Wiki page CRUD tools."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import profile as profile_mod
from server.lib import storage

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP
else:
    # At runtime, for FastMCP usage in register()
    from mcp.server.fastmcp import FastMCP  # noqa: TC002

REQUIRED_FRONTMATTER_FIELDS = ("title", "tags", "links_to", "scope", "sources", "last_ingested")


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_page_write)
    mcp.tool()(wiki_page_get)
    mcp.tool()(wiki_page_list)
    mcp.tool()(wiki_page_delete)


def _validate_frontmatter(fm: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_FRONTMATTER_FIELDS if field not in fm]


def _content_hash(frontmatter: dict[str, Any], body: str) -> str:
    h = hashlib.sha256()
    # Stable-sort keys for deterministic hash
    h.update(json.dumps(frontmatter, sort_keys=True).encode())
    h.update(body.encode())
    return h.hexdigest()


def wiki_page_write(
    slug: str,
    category: str | None,
    frontmatter: dict[str, Any],
    body: str,
    mode: str = "upsert",
) -> str:
    """Create, update, or upsert a wiki page.

    Args:
        slug: page slug (filename stem, lowercase-with-dashes).
        category: directory name under pages/. None = flat (minimal profile).
        frontmatter: dict with required keys: title, tags, links_to, scope, sources, last_ingested.
        body: markdown body text.
        mode: "create" | "update" | "upsert".

    Returns JSON string with {path, created, updated, noop, warning?} or {error}.
    """
    cfg = config_mod.load_config()
    wiki_dir: Path = cfg.wiki_dir
    missing = _validate_frontmatter(frontmatter)
    if missing:
        return json.dumps({"error": f"missing required frontmatter fields: {missing}"})

    warning: str | None = None
    try:
        profile = profile_mod.load_profile(wiki_dir)
    except profile_mod.ProfileError as e:
        return json.dumps({"error": f"profile load failed: {e}"})

    if profile.categories and category and category not in profile.categories:
        warning = (
            f"category {category!r} not in active profile ({profile.name}): {profile.categories}"
        )

    target = storage.page_path(wiki_dir, category, slug)
    exists = target.exists()

    if mode == "create" and exists:
        return json.dumps({"error": f"page exists at {target}"})
    if mode == "update" and not exists:
        return json.dumps({"error": f"not_found: {target} does not exist"})
    if mode not in {"create", "update", "upsert"}:
        return json.dumps({"error": f"invalid mode: {mode!r}"})

    new_content = fm_mod.dump(frontmatter, body)

    with storage.wiki_lock(wiki_dir):
        # Re-check existence under lock so idempotency + created/updated
        # reporting reflect the locked-state truth. Pre-lock `exists` stayed
        # accurate for the mode-error guards above (best-effort by design),
        # but a concurrent writer could have created the page between
        # `target.exists()` at line 80 and lock acquisition here.
        locked_exists = target.exists()
        # Idempotency: on upsert with identical existing content → no-op.
        if mode == "upsert" and locked_exists:
            existing_raw = target.read_text()
            existing_fm, existing_body = fm_mod.parse(existing_raw)
            if _content_hash(existing_fm, existing_body) == _content_hash(frontmatter, body):
                return json.dumps(
                    {
                        "path": str(target),
                        "created": False,
                        "updated": False,
                        "noop": True,
                        "warning": warning,
                    }
                )
        storage.atomic_write(target, new_content)

    return json.dumps(
        {
            "path": str(target),
            "created": not locked_exists,
            "updated": locked_exists,
            "noop": False,
            "warning": warning,
        }
    )


def wiki_page_get(slug: str, category: str | None) -> str:
    """Read a single wiki page.

    Args:
        slug: page slug (filename stem, lowercase-with-dashes).
        category: directory name under pages/. None = flat (minimal profile).

    Returns JSON string with {frontmatter, body, path} or {error: "not_found" | ...}.
    """
    cfg = config_mod.load_config()
    target = storage.page_path(cfg.wiki_dir, category, slug)
    if not target.exists():
        return json.dumps({"error": "not_found", "path": str(target)})
    try:
        fm, body = fm_mod.parse(target.read_text())
    except fm_mod.FrontmatterError as e:
        return json.dumps({"error": f"malformed frontmatter: {e}", "path": str(target)})
    return json.dumps({"frontmatter": fm, "body": body, "path": str(target)})


def wiki_page_list(
    scope_filter: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    linked_from: str | None = None,
    linked_to: str | None = None,
    limit: int = 0,
) -> str:
    """List pages with optional filters.

    Filters:
        scope_filter: match pages whose scope[] contains this value.
        category: match pages under pages/<category>/.
        tags: match pages whose tags[] is a superset of this list.
        linked_from: match pages pointed at by this slug (i.e. slug's links_to).
        linked_to: match pages whose links_to contains this slug.
        limit: 0 = unlimited. Truncation flag in response.
    """
    cfg = config_mod.load_config()
    pages_root = storage.pages_dir(cfg.wiki_dir)
    if not pages_root.exists():
        return json.dumps({"pages": [], "truncated": False})

    tag_set = set(tags or [])

    # Build linked_from map: slug → links_to from that page (for linked_from filter)
    linked_from_targets: set[str] = set()
    if linked_from:
        source_path = None
        for md in pages_root.rglob("*.md"):
            if md.stem == linked_from:
                source_path = md
                break
        if source_path:
            fm, _ = fm_mod.parse(source_path.read_text())
            linked_from_targets = set(fm.get("links_to", []) or [])

    results: list[dict[str, Any]] = []
    for md in sorted(pages_root.rglob("*.md")):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else None
        if category and cat != category:
            continue
        try:
            fm, _ = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue  # skip malformed pages
        page_scope = cast("list[str]", fm.get("scope", []) or [])
        if scope_filter and scope_filter not in page_scope:
            continue
        page_tags = set(fm.get("tags", []) or [])
        if tag_set and not tag_set.issubset(page_tags):
            continue
        if linked_to and linked_to not in (fm.get("links_to", []) or []):
            continue
        if linked_from and md.stem not in linked_from_targets:
            continue
        results.append(
            {
                "title": fm.get("title", ""),
                "slug": md.stem,
                "category": cat,
                "scope": page_scope,
                "tags": list(page_tags),
                "last_ingested": fm.get("last_ingested", ""),
            }
        )

    truncated = False
    if limit > 0 and len(results) > limit:
        results = results[:limit]
        truncated = True

    return json.dumps({"pages": results, "truncated": truncated})


def wiki_page_delete(slug: str, category: str | None) -> str:
    """Delete a page and prune references to it from other pages' links_to frontmatter.

    Args:
        slug: page slug (filename stem, lowercase-with-dashes).
        category: directory name under pages/. None = flat (minimal profile).

    Returns JSON string with {deleted: True, backlinks_updated: [slug, ...], path} or {error}.
    """
    cfg = config_mod.load_config()
    wiki_dir: Path = cfg.wiki_dir
    target = storage.page_path(wiki_dir, category, slug)
    if not target.exists():
        return json.dumps({"error": "not_found", "path": str(target)})

    updated_backlinks: list[str] = []
    with storage.wiki_lock(wiki_dir):
        # Find + update backlinks first, THEN delete the target
        pages_root = storage.pages_dir(wiki_dir)
        for md in pages_root.rglob("*.md"):
            if md == target:
                continue
            try:
                fm, body = fm_mod.parse(md.read_text())
            except fm_mod.FrontmatterError:
                continue
            links: list[str] = cast("list[str]", fm.get("links_to", []) or [])
            if slug in links:
                new_links = [link for link in links if link != slug]
                fm["links_to"] = new_links
                storage.atomic_write(md, fm_mod.dump(fm, body))
                updated_backlinks.append(md.stem)
        target.unlink()
    return json.dumps(
        {
            "deleted": True,
            "backlinks_updated": updated_backlinks,
            "path": str(target),
        }
    )
