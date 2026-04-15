"""Tests for consolidated todo_add (replaces todo_add_child, todo_batch_add_children)."""


def get_registered_tool_names(app):
    """Helper to get all registered tool names from a FastMCP app."""
    return [t.name for t in app._tool_manager.list_tools()]


def test_todo_add_child_tool_does_not_exist():
    """todo_add_child must not be registered — use todo_add(parent=) instead."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.todos import register

    app = FastMCP("test")
    register(app)
    tool_names = get_registered_tool_names(app)
    assert "todo_add_child" not in tool_names, (
        "todo_add_child is still registered — it should be removed; use todo_add(parent=) instead"
    )
    assert "todo_add" in tool_names
