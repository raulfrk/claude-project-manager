"""Minimal HTTP endpoint for receiving inter-server hook calls."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("hook_transport.handler")


def _serialize_result(result: Any) -> Any:
    """Serialize a tool result for JSON response.

    Handles raw Python values (strings, dicts, lists) and ContentBlock
    sequences from FastMCP's convert_result mode.
    """
    if result is None:
        return None
    if isinstance(result, (str, int, float, bool)):
        return result
    if isinstance(result, dict):
        return result
    # Check for ContentBlock sequences before plain lists
    if isinstance(result, (list, tuple)):
        if result and hasattr(result[0], "text"):
            texts = [item.text for item in result if hasattr(item, "text")]
            return texts[0] if len(texts) == 1 else texts
        return list(result)
    # Fallback: stringify
    return str(result)


def create_hook_app(mcp_instance: FastMCP) -> Starlette:
    """Create a Starlette app that dispatches tool calls to the FastMCP registry.

    Routes:
        POST /hook  — accepts {"tool": str, "params": dict}, dispatches to tool
        GET  /health — returns {"status": "ok", "tools": [...]}
    """
    tm = mcp_instance._tool_manager  # noqa: SLF001

    async def handle_hook(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "Invalid JSON body"}, status_code=400)

        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "Body must be a JSON object"}, status_code=400)

        tool_name = body.get("tool")
        if not tool_name or not isinstance(tool_name, str):
            return JSONResponse({"ok": False, "error": "Missing or invalid 'tool' field"}, status_code=400)

        params = body.get("params", {})
        if not isinstance(params, dict):
            return JSONResponse({"ok": False, "error": "'params' must be a JSON object"}, status_code=400)

        tool = tm.get_tool(tool_name)
        if tool is None:
            return JSONResponse(
                {"ok": False, "error": f"Unknown tool: {tool_name}"},
                status_code=404,
            )

        try:
            result = await tm.call_tool(tool_name, params, context=None, convert_result=False)
            return JSONResponse({"ok": True, "result": _serialize_result(result)})
        except Exception as exc:
            logger.exception("Tool %s raised an exception", tool_name)
            return JSONResponse(
                {"ok": False, "error": f"Tool error: {exc}"},
                status_code=500,
            )

    async def health(request: Request) -> JSONResponse:
        tools = [t.name for t in tm.list_tools()]
        return JSONResponse({"status": "ok", "tools": sorted(tools)})

    return Starlette(
        routes=[
            Route("/hook", handle_hook, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
        ],
    )
