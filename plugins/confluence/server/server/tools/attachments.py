"""confluence_list_attachments tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_list_attachments(
        page_id: str,
        limit: int | None = None,
        start: int = 0,
        media_type: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """List attachments on a Confluence page."""
        client = get_client()
        effective_limit = limit or client.config.default_max_results

        params: dict[str, Any] = {"limit": effective_limit, "start": start}
        if media_type:
            params["mediaType"] = media_type
        if filename:
            params["filename"] = filename

        raw = client.get(f"/content/{page_id}/child/attachment", params=params)

        results = []
        for a in raw.get("results", []):
            ext = a.get("extensions", {})
            results.append(
                {
                    "id": a.get("id"),
                    "title": a.get("title"),
                    "media_type": ext.get("mediaType"),
                    "file_size": ext.get("fileSize"),
                    "download_url": a.get("_links", {}).get("download"),
                }
            )

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "next_start": next_start,
        }
