"""Trello lists tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool()
    def get_lists(board_id: str) -> str:
        """Get all lists on a Trello board."""
        client = get_client()
        client.check_board_access(board_id)
        data = client.get(f"/boards/{board_id}/lists")
        return json.dumps(data)

    @app.tool()
    def get_list(list_id: str) -> str:
        """Get a single Trello list by ID."""
        client = get_client()
        data = client.get(f"/lists/{list_id}")
        return json.dumps(data)

    @app.tool()
    def create_list(name: str, board_id: str) -> str:
        """Create a new list on a Trello board."""
        client = get_client()
        client.check_board_access(board_id)
        data = client.post("/lists", params={"name": name, "idBoard": board_id})
        return json.dumps(data)

    @app.tool()
    def update_list(
        list_id: str,
        name: str | None = None,
        closed: bool | None = None,
    ) -> str:
        """Update a Trello list (name and/or closed status)."""
        client = get_client()
        params: dict[str, str | bool] = {}
        if name is not None:
            params["name"] = name
        if closed is not None:
            params["closed"] = closed
        data = client.put(f"/lists/{list_id}", params=params)
        return json.dumps(data)
