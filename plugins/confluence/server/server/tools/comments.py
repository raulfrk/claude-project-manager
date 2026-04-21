"""confluence_list_comments tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.lib.client import get_client
from server.lib.markdown import html_to_markdown

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_list_comments(
        page_id: str,
        location: str | None = None,
        limit: int | None = None,
        start: int = 0,
    ) -> dict[str, Any]:
        """List comments on a Confluence page."""
        client = get_client()
        effective_limit = limit or client.config.default_max_results

        params: dict[str, Any] = {
            "limit": effective_limit,
            "start": start,
            "expand": "body.view,version",
        }
        if location and location != "all":
            params["location"] = location

        raw = client.get(f"/content/{page_id}/child/comment", params=params)

        results = []
        for c in raw.get("results", []):
            version = c.get("version", {})
            author = version.get("by", {}).get("displayName") if version else None
            body_html = c.get("body", {}).get("view", {}).get("value", "")
            results.append(
                {
                    "id": c.get("id"),
                    "author": author,
                    "created": version.get("when"),
                    "body_md": html_to_markdown(body_html),
                    "location": c.get("extensions", {}).get("location"),
                }
            )

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "next_start": next_start,
        }
