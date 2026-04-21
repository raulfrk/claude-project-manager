"""confluence_list_spaces tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_list_spaces(
        type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        start: int = 0,
    ) -> dict[str, Any]:
        """List Confluence spaces."""
        client = get_client()
        effective_limit = limit or client.config.default_max_results

        params: dict[str, Any] = {"limit": effective_limit, "start": start}
        if type:
            params["type"] = type
        if status:
            params["status"] = status

        raw = client.get("/space", params=params)

        results = []
        for s in raw.get("results", []):
            results.append(
                {
                    "key": s.get("key"),
                    "name": s.get("name"),
                    "type": s.get("type"),
                    "url": s.get("_links", {}).get("webui"),
                }
            )

        has_next = bool(raw.get("_links", {}).get("next"))
        next_start = (start + effective_limit) if has_next else None

        return {
            "results": results,
            "count": len(results),
            "next_start": next_start,
        }
