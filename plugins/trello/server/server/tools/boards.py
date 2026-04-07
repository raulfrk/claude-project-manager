"""Trello board tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib.client import get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    @app.tool(description="List all boards for the authenticated user.")
    def list_boards() -> str:
        client = get_client()
        raw = client.get("/members/me/boards")
        boards = raw if isinstance(raw, list) else []
        if client._config.allowed_board_ids:
            boards = [
                b
                for b in boards
                if isinstance(b, dict) and b.get("id") in client._config.allowed_board_ids
            ]
        return json.dumps(boards)

    @app.tool(description="Get a single board by ID.")
    def get_board(board_id: str) -> str:
        client = get_client()
        client.check_board_access(board_id)
        board = client.get(f"/boards/{board_id}")
        return json.dumps(board)

    @app.tool(description="Update a board's name or description.")
    def update_board(board_id: str, name: str | None = None, desc: str | None = None) -> str:
        client = get_client()
        params: dict[str, str] = {}
        if name is not None:
            params["name"] = name
        if desc is not None:
            params["desc"] = desc
        board = client.put(f"/boards/{board_id}", params=params)
        return json.dumps(board)
