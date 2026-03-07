"""Shared test fixtures for proj server tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
)


@pytest.fixture(autouse=True)
def reset_session_state() -> None:
    """Reset session state before each test to prevent cross-test contamination."""
    state.clear_session_active()
    yield  # type: ignore[misc]
    state.clear_session_active()


@pytest.fixture(autouse=True)
def _isolate_sandbox_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent sandbox detection from reading the real ~/.claude/settings.local.json.

    Tests that explicitly need sandbox mode will override these monkeypatches
    with their own paths.
    """
    nonexistent = tmp_path / "nonexistent-local-settings.json"
    monkeypatch.setattr("server.lib.perms_helpers._USER_LOCAL_SETTINGS", nonexistent)


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    c = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(c)
    return c


def setup_project(cfg: ProjConfig, name: str, repo_path: str) -> None:
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=repo_path)],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)


@pytest.fixture()
def mcp_app(cfg: ProjConfig):  # type: ignore[no-untyped-def]
    """Return a configured FastMCP app with all tools registered."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, content, context, git, migrate, perms_sync, projects, todos

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)
    content.register(app)
    git.register(app)
    context.register(app)
    migrate.register(app)
    perms_sync.register(app)
    return app


async def call_tool(app: Any, tool_name: str, **kwargs: Any) -> Any:
    """Helper to call an MCP tool by name."""
    raw = await app.call_tool(tool_name, kwargs)
    # FastMCP may return a list or a (list, meta) tuple
    items = raw[0] if isinstance(raw, tuple) else raw
    if items and hasattr(items[0], "text"):
        return items[0].text
    # Empty list means the tool returned ""
    return ""
