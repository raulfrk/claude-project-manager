"""Pages tools: get_page (T12). list_pages + get_page_tree added in T14 + T15."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.lib.client import get_client
from server.lib.markdown import html_to_markdown

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    _register_get_page(mcp)


def _register_get_page(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_get_page(
        page_id: str | None = None,
        title: str | None = None,
        space_key: str | None = None,
        format: str = "md",
        include_labels: bool = False,
        include_ancestors: bool = False,
    ) -> dict[str, Any]:
        """Fetch a Confluence page by id OR (title + space_key). Returns markdown body."""
        if page_id is None and title is None:
            raise ValueError("Either page_id or title must be provided")
        if title is not None and space_key is None:
            raise ValueError("title requires space_key")
        if format not in ("md", "html", "both"):
            raise ValueError("format must be md|html|both")

        client = get_client()
        if space_key:
            client.check_space_allowed(space_key)

        expand_parts = ["body.view", "version", "space"]
        if include_ancestors:
            expand_parts.append("ancestors")
        if include_labels:
            expand_parts.append("metadata.labels")
        expand = ",".join(expand_parts)

        if page_id:
            raw = client.get(f"/content/{page_id}", params={"expand": expand})
        else:
            listing = client.get(
                "/content",
                params={
                    "type": "page",
                    "spaceKey": space_key,
                    "title": title,
                    "expand": expand,
                    "limit": 1,
                },
            )
            results = listing.get("results", [])
            if not results:
                from server.lib.errors import NotFoundError

                raise NotFoundError(f"Page not found: {space_key}/{title}")
            raw = results[0]

        resolved_space_key = raw.get("space", {}).get("key")
        if resolved_space_key:
            client.check_space_allowed(resolved_space_key)

        body_html = raw.get("body", {}).get("view", {}).get("value", "")
        out: dict[str, Any] = {
            "page_id": raw.get("id"),
            "title": raw.get("title"),
            "space_key": resolved_space_key,
            "url": raw.get("_links", {}).get("webui"),
            "version": raw.get("version", {}).get("number"),
        }
        if format in ("md", "both"):
            out["body_md"] = html_to_markdown(body_html)
        if format in ("html", "both"):
            out["body_html"] = body_html
        if include_labels:
            labels_block = raw.get("metadata", {}).get("labels", {})
            out["labels"] = [lb.get("name") for lb in labels_block.get("results", [])]
        if include_ancestors:
            out["ancestors"] = [
                {"id": a.get("id"), "title": a.get("title")} for a in raw.get("ancestors", [])
            ]
        return out
