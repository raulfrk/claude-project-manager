"""Trello board tools."""
from __future__ import annotations
import json
from mcp.server.fastmcp import FastMCP
from server.lib.client import get_client

def register(app: FastMCP) -> None:
    @app.tool(description="List all boards for the authenticated user.")
    def list_boards() -> str:
        client = get_client()
        boards = client.get("/members/me/boards")
        return json.dumps(boards)

    @app.tool(description="Get a single board by ID.")
    def get_board(board_id: str) -> str:
        client = get_client()
        board = client.get(f"/boards/{board_id}")
        return json.dumps(board)

    @app.tool(description="Create a new board.")
    def create_board(name: str, desc: str = "") -> str:
        client = get_client()
        params = {"name": name}
        if desc:
            params["desc"] = desc
        board = client.post("/boards", params=params)
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

    @app.tool(description="Delete a board permanently.")
    def delete_board(board_id: str) -> str:
        client = get_client()
        client.delete(f"/boards/{board_id}")
        return json.dumps({"deleted": True, "board_id": board_id})
