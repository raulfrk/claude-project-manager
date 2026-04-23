"""Shared pytest fixtures for wiki plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from server.lib import config as config_mod
from server.lib.models import WikiConfig
from server.lib.profile import get_builtin, save_profile


@pytest.fixture
def wiki_cfg_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a temp config path + redirect ~/.claude/wiki.yaml to it.

    Tests that load config will see the temp file instead of the user's real one.
    """
    cfg_path = tmp_path / "wiki.yaml"
    monkeypatch.setattr("server.lib.config._DEFAULT_CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture
def wiki_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a temp ~/.claude/wiki/ root + redirect config's wiki_dir there."""
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "pages").mkdir()
    return root


@pytest.fixture
def wiki_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Full wiki setup: config file + wiki dir + software profile."""
    cfg_path = tmp_path / "wiki.yaml"
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "pages").mkdir()

    monkeypatch.setattr(config_mod, "_DEFAULT_CONFIG_PATH", cfg_path)
    cfg = WikiConfig(enabled=True, wiki_dir=wiki_dir)
    config_mod.save_config(cfg)
    save_profile(wiki_dir, get_builtin("software"))
    return {"cfg_path": cfg_path, "wiki_dir": wiki_dir}


@pytest.fixture
def proj_yaml_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect proj.yaml lookup in scope.py to a temp path."""
    p = tmp_path / "proj.yaml"
    monkeypatch.setattr("server.tools.scope._PROJ_YAML_PATH", p)
    return p


@pytest.fixture
def mcp_app(wiki_setup: dict[str, Path]) -> FastMCP:
    """FastMCP instance with wiki tools registered (expand as tools land)."""
    from server.tools import index, links, lint, log, page, scope, search

    mcp: FastMCP = FastMCP("wiki-test")
    page.register(mcp)
    log.register(mcp)
    index.register(mcp)
    links.register(mcp)
    scope.register(mcp)
    search.register(mcp)
    lint.register(mcp)
    return mcp


async def call_tool(app: FastMCP, tool_name: str, **kwargs: Any) -> str:
    """Invoke an MCP tool + return the text payload."""
    raw = await app.call_tool(tool_name, kwargs)
    items = raw[0] if isinstance(raw, tuple) else raw
    if items and hasattr(items[0], "text"):
        return items[0].text  # type: ignore[no-any-return]
    return ""


def _write_page(wiki_dir: Path, category: str | None, slug: str, **fm_overrides: Any) -> None:
    """Write wiki page w/ default frontmatter + overridable fields.

    Body always 'body'. Category None = flat layout. Use in tests needing
    known page to exist without full wiki_page_write MCP path.
    """
    import json

    base: dict[str, Any] = {
        "title": slug.replace("-", " ").title(),
        "tags": [],
        "links_to": [],
        "scope": ["global"],
        "sources": [],
        "last_ingested": "2026-04-23T10:00:00Z",
    }
    base.update(fm_overrides)
    fm_lines = "\n".join(f"{k}: {json.dumps(v)}" for k, v in base.items())
    path = wiki_dir / "pages"
    if category:
        path = path / category
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{slug}.md").write_text(f"---\n{fm_lines}\n---\nbody")
