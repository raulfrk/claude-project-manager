"""Regression tests for perms server package structure.

Catches the incorrect flat layout (files in server/ project root instead of
server/server/ package subdirectory) that causes the MCP server to fail at
runtime with: ModuleNotFoundError: No module named 'server'

The pyproject.toml entry point 'perms-server = "server.main:main"' requires
the server/ package to exist as a subdirectory of the project root.
"""

from __future__ import annotations

import importlib.util


def test_server_main_importable() -> None:
    """server.main must be importable — the perms-server entry point depends on it.

    If this fails with ModuleNotFoundError, the source files are in the wrong
    location. They must be in plugins/perms/server/server/ (not server/ root).
    """
    spec = importlib.util.find_spec("server.main")
    assert spec is not None, (
        "server.main is not importable. "
        "Source files must be in plugins/perms/server/server/ (the server/ package), "
        "not directly in plugins/perms/server/ (the uv project root). "
        "The entry point 'perms-server = \"server.main:main\"' requires this structure."
    )


def test_server_main_has_callable_main() -> None:
    """server.main:main must be a callable — the script entry point calls it."""
    from server.main import main, mcp  # noqa: PLC0415

    assert callable(main), "server.main.main must be callable"
    assert mcp is not None, "server.main.mcp (FastMCP instance) must exist"


def test_server_lib_importable() -> None:
    """server.lib must be importable — all tools depend on it."""
    spec = importlib.util.find_spec("server.lib")
    assert spec is not None, "server.lib not importable — check package structure"


def test_server_tools_importable() -> None:
    """server.tools must be importable — all MCP tools live here."""
    spec = importlib.util.find_spec("server.tools")
    assert spec is not None, "server.tools not importable — check package structure"
