"""Shared test fixtures for proj server tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from server.lib import state, storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
)


@pytest.fixture(params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    """Use asyncio backend only for anyio tests (trio is not installed)."""
    return str(request.param)


@pytest.fixture(autouse=True)
def reset_session_state() -> Generator[None, None, None]:
    """Reset session state before each test to prevent cross-test contamination."""
    state.clear_session_active()
    yield
    state.clear_session_active()


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    c = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(c)
    return c


def setup_project(cfg: ProjConfig, name: str, repo_path: str) -> None:
    from server.lib.db import ensure_db

    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True)
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    # schema_version: 3 required so require_current() passes (Phase 3 guard)
    (proj_dir / "proj.yaml").write_text(f"name: {name}\nschema_version: 3\n")
    # Initialize the SQL database so storage functions work
    ensure_db(cfg, name)
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=repo_path)],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)


def make_v3_project(tmp_path: Path, cfg: ProjConfig, name: str = "demo") -> tuple[ProjConfig, str]:
    """Create a minimal v3 project fixture for SQL-only storage tests.

    1. Creates tracking_dir/<name>/proj.yaml with schema_version: 3
    2. Calls ensure_db to create SQL tables
    3. Returns (cfg, name)
    """
    from server.lib.db import ensure_db

    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "proj.yaml").write_text(f"name: {name}\nschema_version: 3\n")
    ensure_db(cfg, name)
    return cfg, name


@pytest.fixture()
def mcp_app(cfg: ProjConfig) -> FastMCP:
    """Return a configured FastMCP app with all tools registered."""
    from server.tools import (
        config,
        content,
        context,
        git,
        migrate,
        perms_sync,
        projects,
        todos,
        tracking_git,
    )

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)
    content.register(app)
    git.register(app)
    context.register(app)
    migrate.register(app)
    perms_sync.register(app)
    tracking_git.register(app)
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
