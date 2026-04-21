"""confluence_search tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _escape_cql_literal(s: str) -> str:
    """Escape backslash + double-quote for use inside a CQL double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_search(
        cql: str | None = None,
        text: str | None = None,
        space_key: str | None = None,
        type: str | None = None,
        limit: int | None = None,
        start: int = 0,
        expand: str | None = None,
    ) -> dict[str, Any]:
        """Search Confluence content via CQL or free text.

        Either `cql` (raw CQL) OR `text` (wrapped as text search) must be given.
        """
        if cql is None and text is None:
            raise ValueError("Either cql or text must be provided")

        client = get_client()
        if space_key:
            client.check_space_allowed(space_key)

        effective_cql = cql if cql is not None else f'text ~ "{_escape_cql_literal(text)}"'  # type: ignore[arg-type]
        clauses: list[str] = []
        if cql is None:
            if space_key:
                clauses.append(f'space = "{_escape_cql_literal(space_key)}"')
            if type:
                clauses.append(f'type = "{_escape_cql_literal(type)}"')
        if clauses:
            effective_cql = effective_cql + " AND " + " AND ".join(clauses)

        if client.config.allowed_spaces and "space" not in effective_cql.lower():
            space_clause = " OR ".join(
                f'space = "{_escape_cql_literal(k)}"' for k in client.config.allowed_spaces
            )
            effective_cql = f"({effective_cql}) AND ({space_clause})"

        effective_limit = limit or client.config.default_max_results
        params: dict[str, Any] = {
            "cql": effective_cql,
            "limit": effective_limit,
            "start": start,
        }
        if expand:
            params["expand"] = expand

        raw = client.get("/search", params=params)

        results = []
        for entry in raw.get("results", []):
            content = entry.get("content", {})
            results.append(
                {
                    "page_id": content.get("id"),
                    "type": content.get("type"),
                    "title": content.get("title"),
                    "space_key": content.get("space", {}).get("key"),
                    "url": entry.get("url") or entry.get("_links", {}).get("webui"),
                    "excerpt": entry.get("excerpt"),
                    "last_modified": entry.get("lastModified"),
                }
            )

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "total": raw.get("totalSize"),
            "next_start": next_start,
        }
