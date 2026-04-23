"""BM25 search MCP tools: wiki_search_bm25 + wiki_search_index_refresh."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from server.lib import bm25 as bm25_mod
from server.lib import config as config_mod
from server.lib import frontmatter as fm_mod
from server.lib import storage

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP
else:
    from mcp.server.fastmcp import FastMCP  # noqa: TC002


_SNIPPET_CTX_CHARS = 80


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_search_bm25)
    mcp.tool()(wiki_search_index_refresh)


def _extract_snippet(body: str, query_tokens: list[str]) -> str:
    """Grab a small window around the first query-token occurrence."""
    low = body.lower()
    for tok in query_tokens:
        idx = low.find(tok)
        if idx >= 0:
            start = max(0, idx - _SNIPPET_CTX_CHARS)
            end = min(len(body), idx + len(tok) + _SNIPPET_CTX_CHARS)
            return body[start:end].replace("\n", " ").strip()
    return body[:160].replace("\n", " ").strip()


def _page_metadata(
    wiki_dir: Path,
    slug: str,
) -> tuple[str | None, dict[str, Any], str]:
    """Return (category, frontmatter, body) for a given slug, or (None, {}, '') if missing."""
    pages_root = storage.pages_dir(wiki_dir)
    for md in pages_root.rglob(f"{slug}.md"):
        rel = md.relative_to(pages_root)
        cat = rel.parts[0] if len(rel.parts) > 1 else None
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            return None, {}, ""
        return cat, fm, body
    return None, {}, ""


def wiki_search_bm25(
    query: str,
    limit: int = 20,
    category: str | None = None,
    tags: list[str] | None = None,
    scope_filter: str | None = None,
) -> str:
    """BM25 keyword search over wiki pages. Filters applied post-ranking.

    Returns JSON {hits: [{slug, score, snippet, category, tags, scope}]}.
    """
    cfg = config_mod.load_config()
    idx = bm25_mod.load_or_rebuild(cfg.wiki_dir)
    raw_hits = idx.query(query, top_k=limit * 3 if (category or tags or scope_filter) else limit)

    query_tokens = bm25_mod.tokenize(query)
    tag_set = set(tags or [])
    results: list[dict[str, Any]] = []
    for hit in raw_hits:
        cat, fm, body = _page_metadata(cfg.wiki_dir, hit["slug"])
        if cat is None:
            continue
        if category and cat != category:
            continue
        page_tags = set(fm.get("tags", []) or [])
        if tag_set and not tag_set.issubset(page_tags):
            continue
        page_scope: list[str] = fm.get("scope", []) or []
        if scope_filter and scope_filter not in page_scope:
            continue
        results.append(
            {
                "slug": hit["slug"],
                "score": hit["score"],
                "snippet": _extract_snippet(body, query_tokens),
                "category": cat,
                "tags": list(page_tags),
                "scope": page_scope,
            }
        )
        if len(results) >= limit:
            break
    return json.dumps({"hits": results})


def wiki_search_index_refresh() -> str:
    """Force full rebuild of the BM25 sidecar index."""
    cfg = config_mod.load_config()
    start = time.monotonic()
    idx = bm25_mod.rebuild_index(cfg.wiki_dir)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return json.dumps({"pages_indexed": idx.doc_count, "elapsed_ms": elapsed_ms})
