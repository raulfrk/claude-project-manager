"""Tests for proj_sync unified integration dispatcher (605.6)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    import pytest

from server.tools import jira_sync, sync, todoist_full_sync, trello_full_sync


def _make_sync_app() -> FastMCP:
    """FastMCP app with only proj_sync registered."""
    app = FastMCP("test-sync")
    sync.register(app)
    return app


def test_old_full_sync_tools_not_registered() -> None:
    """proj_todoist/trello/jira_full_sync must not be registered by their modules."""
    # todoist_full_sync.register() is now a no-op
    app_td = FastMCP("test-td")
    todoist_full_sync.register(app_td)
    names_td = [t.name for t in app_td._tool_manager.list_tools()]
    assert "proj_todoist_full_sync" not in names_td

    # trello_full_sync.register() is now a no-op
    app_tr = FastMCP("test-tr")
    trello_full_sync.register(app_tr)
    names_tr = [t.name for t in app_tr._tool_manager.list_tools()]
    assert "proj_trello_full_sync" not in names_tr

    # jira_sync.register() only registers proj_jira_map and proj_jira_apply
    app_jr = FastMCP("test-jr")
    jira_sync.register(app_jr)
    names_jr = [t.name for t in app_jr._tool_manager.list_tools()]
    assert "proj_jira_full_sync" not in names_jr

    # proj_sync IS registered by sync.register()
    app_s = _make_sync_app()
    names_s = [t.name for t in app_s._tool_manager.list_tools()]
    assert "proj_sync" in names_s


def test_proj_sync_rejects_unknown_integration() -> None:
    """proj_sync with unknown integration returns error JSON."""
    app = _make_sync_app()
    tool = app._tool_manager.get_tool("proj_sync")
    assert tool is not None
    result = tool.fn(integration="unknown")
    data = json.loads(result)
    assert "error" in data
    assert "unknown" in data["error"] or "Unknown" in data["error"]


def test_proj_sync_dispatches_todoist(monkeypatch: pytest.MonkeyPatch) -> None:
    """proj_sync(integration='todoist') calls _run_todoist_full_sync."""
    calls: list[str] = []

    def fake_todoist(project_name: str | None = None, **kwargs: object) -> str:
        calls.append("todoist")
        return json.dumps({"status": "success", "summary": {}})

    monkeypatch.setattr(todoist_full_sync, "_run_todoist_full_sync", fake_todoist)

    app = _make_sync_app()
    tool = app._tool_manager.get_tool("proj_sync")
    assert tool is not None
    result = tool.fn(integration="todoist")
    data = json.loads(result)
    assert data.get("status") == "success"
    assert calls == ["todoist"]


def test_proj_sync_dispatches_jira(monkeypatch: pytest.MonkeyPatch) -> None:
    """proj_sync(integration='jira') calls _run_jira_full_sync."""
    calls: list[str] = []

    def fake_jira(project_name: str | None = None, **kwargs: object) -> str:
        calls.append("jira")
        return json.dumps({"status": "success", "summary": {}})

    monkeypatch.setattr(jira_sync, "_run_jira_full_sync", fake_jira)

    app = _make_sync_app()
    tool = app._tool_manager.get_tool("proj_sync")
    assert tool is not None
    result = tool.fn(integration="jira")
    data = json.loads(result)
    assert data.get("status") == "success"
    assert calls == ["jira"]


def test_proj_sync_dispatches_trello(monkeypatch: pytest.MonkeyPatch) -> None:
    """proj_sync(integration='trello') calls _run_trello_full_sync."""
    calls: list[str] = []

    def fake_trello(project_name: str | None = None, **kwargs: object) -> str:
        calls.append("trello")
        return json.dumps({"status": "success", "summary": {}})

    monkeypatch.setattr(trello_full_sync, "_run_trello_full_sync", fake_trello)

    app = _make_sync_app()
    tool = app._tool_manager.get_tool("proj_sync")
    assert tool is not None
    result = tool.fn(integration="trello")
    data = json.loads(result)
    assert data.get("status") == "success"
    assert calls == ["trello"]
