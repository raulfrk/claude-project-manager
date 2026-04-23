"""Wiki page CRUD tools."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

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
    if not cfg.enabled:
        return json.dumps({"error": "wiki disabled; run /wiki:init first"})

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

    # Idempotency: on upsert with identical existing content → no-op.
    if mode == "upsert" and exists:
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

    with storage.wiki_lock(wiki_dir):
        storage.atomic_write(target, new_content)

    return json.dumps(
        {
            "path": str(target),
            "created": not exists,
            "updated": exists,
            "noop": False,
            "warning": warning,
        }
    )
