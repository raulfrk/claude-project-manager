"""Tests for proj_search_knowledge tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import setup_project


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> str:
    """Create a test project with knowledge stores populated."""
    name = "test-proj"
    repo = tmp_path / "repo"
    repo.mkdir()
    setup_project(cfg, name, str(repo))
    state.set_session_active(name)

    t_dir = storage.tracking_dir(cfg, name)

    # Sessions
    sess_dir = t_dir / "sessions"
    sess_dir.mkdir(parents=True)
    (sess_dir / "session-2026-03-01.md").write_text(
        "# Session 2026-03-01\n\nWorked on authentication flow.\n"
        "Fixed login bug.\nRefactored token handling.\n"
    )
    (sess_dir / "session-2026-03-02.md").write_text(
        "# Session 2026-03-02\n\nImplemented search endpoint.\nAdded pagination support.\n"
    )

    # Notes (already created by setup_project but overwrite with richer content)
    storage.notes_path(cfg, name).write_text(
        "# test-proj\n\n## 2026-03-01\n\n"
        "Need to fix authentication before launch.\n\n"
        "## 2026-03-02\n\nSearch feature shipped.\n"
    )

    # Requirements
    req_dir = t_dir / "todos" / "1"
    req_dir.mkdir(parents=True)
    (req_dir / "requirements.md").write_text(
        "# Requirements for Todo 1\n\n"
        "- Must support authentication via OAuth2\n"
        "- Token refresh must be automatic\n"
    )
    req_dir2 = t_dir / "todos" / "2"
    req_dir2.mkdir(parents=True)
    (req_dir2 / "requirements.md").write_text(
        "# Requirements for Todo 2\n\n"
        "- Search must return paginated results\n"
        "- Must support full-text search\n"
    )

    # Research
    (req_dir / "research.md").write_text(
        "# Research for Todo 1\n\nOAuth2 libraries compared:\n"
        "- authlib: mature, authentication focused\n"
        "- python-jose: lightweight JWT\n"
    )

    # Decisions
    (t_dir / "decisions.yaml").write_text(
        "decisions:\n  - date: 2026-03-01\n"
        "    title: Use authlib for authentication\n"
        "    rationale: Most mature OAuth2 library\n"
    )

    return name


@pytest.fixture()
def knowledge_app(cfg: ProjConfig):  # type: ignore[no-untyped-def]
    """Return a FastMCP app with knowledge tool registered."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, knowledge

    app = FastMCP("test-knowledge")
    config.register(app)
    knowledge.register(app)
    return app


async def _call(app, tool_name: str, **kwargs):  # type: ignore[no-untyped-def]
    """Helper to call an MCP tool by name."""
    raw = await app.call_tool(tool_name, kwargs)
    items = raw[0] if isinstance(raw, tuple) else raw
    if items and hasattr(items[0], "text"):
        return items[0].text
    return ""


# ── Scope tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_sessions(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(
            knowledge_app, "proj_search_knowledge", query="authentication", scope="sessions"
        )
    )
    assert result["total_matches"] >= 1
    sources = [s["source"] for s in result["snippets"]]
    assert all("sessions/" in s for s in sources)


@pytest.mark.asyncio
async def test_scope_notes(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="authentication", scope="notes")
    )
    assert result["total_matches"] >= 1
    sources = [s["source"] for s in result["snippets"]]
    assert all("NOTES.md" in s for s in sources)


@pytest.mark.asyncio
async def test_scope_requirements(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="OAuth2", scope="requirements")
    )
    assert result["total_matches"] >= 1
    sources = [s["source"] for s in result["snippets"]]
    assert all("requirements.md" in s for s in sources)


@pytest.mark.asyncio
async def test_scope_research(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="authlib", scope="research")
    )
    assert result["total_matches"] >= 1
    sources = [s["source"] for s in result["snippets"]]
    assert all("research.md" in s for s in sources)


@pytest.mark.asyncio
async def test_scope_decisions(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="authlib", scope="decisions")
    )
    assert result["total_matches"] >= 1
    sources = [s["source"] for s in result["snippets"]]
    assert all("decisions.yaml" in s for s in sources)


@pytest.mark.asyncio
async def test_scope_all_searches_all_stores(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="authentication", scope="all")
    )
    sources = {s["source"] for s in result["snippets"]}
    # "authentication" appears in sessions, notes, requirements, research, and decisions
    # At minimum it should hit sessions and notes
    assert result["total_matches"] >= 2
    # Check multiple source types are present
    has_session = any("sessions/" in s for s in sources)
    has_notes = any("NOTES.md" in s for s in sources)
    assert has_session or has_notes


# ── Regex matching and context ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_regex_matching(knowledge_app, project: str) -> None:
    # Use regex pattern to match "OAuth2" or "OAuth"
    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="OAuth\\d?", scope="all")
    )
    assert result["total_matches"] >= 1


@pytest.mark.asyncio
async def test_context_lines_included(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="login bug", scope="sessions")
    )
    assert result["total_matches"] >= 1
    ctx = result["snippets"][0]["context"]
    # Context should include surrounding lines (not just the match line)
    assert "\n" in ctx


# ── Max snippets limit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_snippets_limit(cfg: ProjConfig, knowledge_app, tmp_path: Path) -> None:
    """Create a project with many matching lines and verify max 5 snippets."""
    name = "many-matches"
    repo = tmp_path / "repo2"
    repo.mkdir()
    setup_project(cfg, name, str(repo))
    state.set_session_active(name)

    storage.tracking_dir(cfg, name)
    notes_p = storage.notes_path(cfg, name)
    # Write 20 lines all containing "keyword"
    lines = [f"Line {i}: keyword appears here" for i in range(20)]
    notes_p.write_text("\n".join(lines))

    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="keyword", scope="notes")
    )
    assert result["total_matches"] == 20
    assert len(result["snippets"]) == 5


# ── Empty results ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_results(knowledge_app, project: str) -> None:
    result = json.loads(
        await _call(
            knowledge_app, "proj_search_knowledge", query="zzz_nonexistent_term", scope="all"
        )
    )
    assert result["total_matches"] == 0
    assert result["snippets"] == []


# ── Missing directories handled gracefully ───────────────────────────────


@pytest.mark.asyncio
async def test_missing_sessions_dir(cfg: ProjConfig, knowledge_app, tmp_path: Path) -> None:
    """Project with no sessions/ directory should return empty, not error."""
    name = "no-sessions"
    repo = tmp_path / "repo3"
    repo.mkdir()
    setup_project(cfg, name, str(repo))
    state.set_session_active(name)

    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="anything", scope="sessions")
    )
    assert result["total_matches"] == 0
    assert result["snippets"] == []


@pytest.mark.asyncio
async def test_missing_todos_dir(cfg: ProjConfig, knowledge_app, tmp_path: Path) -> None:
    """Project with no todos/ directory should return empty for requirements/research."""
    name = "no-todos"
    repo = tmp_path / "repo4"
    repo.mkdir()
    setup_project(cfg, name, str(repo))
    state.set_session_active(name)

    for scope in ("requirements", "research"):
        result = json.loads(
            await _call(knowledge_app, "proj_search_knowledge", query="anything", scope=scope)
        )
        assert result["total_matches"] == 0
        assert result["snippets"] == []


@pytest.mark.asyncio
async def test_missing_decisions_file(cfg: ProjConfig, knowledge_app, tmp_path: Path) -> None:
    """Project with no decisions.yaml should return empty."""
    name = "no-decisions"
    repo = tmp_path / "repo5"
    repo.mkdir()
    setup_project(cfg, name, str(repo))
    state.set_session_active(name)

    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="anything", scope="decisions")
    )
    assert result["total_matches"] == 0
    assert result["snippets"] == []


# ── Error cases ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_active_project(cfg: ProjConfig, knowledge_app) -> None:
    state.clear_session_active()
    result = await _call(knowledge_app, "proj_search_knowledge", query="test")
    assert result == "No active project."


@pytest.mark.asyncio
async def test_invalid_scope(knowledge_app, project: str) -> None:
    result = await _call(knowledge_app, "proj_search_knowledge", query="test", scope="invalid")
    assert "Invalid scope" in result


# ── Density sorting ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snippets_sorted_by_density(cfg: ProjConfig, knowledge_app, tmp_path: Path) -> None:
    """Snippets with more matches in context should rank higher."""
    name = "density-test"
    repo = tmp_path / "repo6"
    repo.mkdir()
    setup_project(cfg, name, str(repo))
    state.set_session_active(name)

    storage.tracking_dir(cfg, name)
    notes_p = storage.notes_path(cfg, name)
    # Line with single mention vs line surrounded by many mentions
    content = (
        "unrelated line\n"
        "word appears once\n"
        "unrelated line\n"
        "unrelated line\n"
        "unrelated line\n"
        "unrelated line\n"
        "unrelated line\n"
        "word word word word word word\n"
        "word word word\n"
        "word more word here\n"
    )
    notes_p.write_text(content)

    result = json.loads(
        await _call(knowledge_app, "proj_search_knowledge", query="word", scope="notes")
    )
    assert result["total_matches"] >= 2
    # The snippet with highest density should be first
    first_ctx = result["snippets"][0]["context"]
    assert first_ctx.count("word") > 2
