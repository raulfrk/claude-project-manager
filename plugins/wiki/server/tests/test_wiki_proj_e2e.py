"""Cross-plugin e2e integration test: proj.notes_append → wiki.wiki_log_append.

Exercises the hook path in-process:
1. proj plugin's notes_append tool appends to a project's NOTES.md
2. wiki plugin's wiki_log_append writes a log entry (simulating what the router
   would fire given sync.wiki.capture_notes_as_log = true in proj.yaml)
3. log.md reflects the note

Uses FastMCP's in-process call_tool harness (no subprocess, no sockets).
The router param-mapping logic is covered by plugins/router/server/tests/;
this test focuses on the proj↔wiki tool contract end-to-end.

Namespace collision note: both proj and wiki packages are named ``server``.
We resolve this by:
  1. Setting HOME before any imports (Path.home() reads $HOME on POSIX).
  2. Temporarily adding the proj source dir to sys.path, importing + registering
     proj context tools, then removing proj from sys.path and sys.modules.
  3. wiki's ``server`` package is already installed in this venv and is unaffected.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROJ_SRC = _REPO_ROOT / "plugins" / "proj" / "server"


def _setup_isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Create a scratch file-system layout under tmp_path.

    Returns a dict of named paths (home, claude_dir, tracking_dir, wiki_dir).
    HOME + PROJ_CONFIG + WIKI_CONFIG env vars are patched so both plugins
    resolve configs to this temp tree.
    """
    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)

    tracking_dir = home / "projects" / "tracking"
    tracking_dir.mkdir(parents=True)
    proj_dir = tracking_dir / "test-project"
    proj_dir.mkdir()
    (proj_dir / "NOTES.md").write_text("")

    proj_yaml = {
        "tracking_dir": str(tracking_dir),
        "projects_base_dir": str(home / "projects"),
        "default_priority": "medium",
        "sync": {
            "wiki": {
                "enabled": True,
                "capture_notes_as_log": True,
                "auto_ingest_sessions": False,
                "replace_notes_md": False,
                "bootstrap_docs": [],
            }
        },
    }
    (claude_dir / "proj.yaml").write_text(yaml.safe_dump(proj_yaml))
    (claude_dir / "proj-session.yaml").write_text(yaml.safe_dump({"active": "test-project"}))

    wiki_dir = claude_dir / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "config.yaml").write_text("profile: minimal\n")
    (wiki_dir / "pages").mkdir()
    (wiki_dir / "log.md").write_text("")

    wiki_yaml = {
        "enabled": True,
        "wiki_dir": str(wiki_dir),
        "reingest_cooldown_hours": 24,
    }
    (claude_dir / "wiki.yaml").write_text(yaml.safe_dump(wiki_yaml))

    # Patch env vars.  HOME is read by Path.home() on POSIX.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PROJ_CONFIG", str(claude_dir / "proj.yaml"))
    monkeypatch.setenv("WIKI_CONFIG", str(claude_dir / "wiki.yaml"))

    return {
        "home": home,
        "claude_dir": claude_dir,
        "tracking_dir": tracking_dir,
        "wiki_dir": wiki_dir,
    }


def _build_proj_app() -> FastMCP:
    """Load proj plugin's context tools into an isolated FastMCP instance.

    Both proj and wiki use a top-level package named ``server``; evicting
    proj's modules before returning lets subsequent ``from server.tools
    import ...`` resolve to wiki's installed package.

    Temporarily adds plugins/proj/server to sys.path, imports + registers,
    then removes all proj ``server.*`` modules from sys.modules so the
    wiki plugin's ``server`` package (installed in this venv) remains the
    sole occupant of that namespace.
    """
    proj_src_str = str(_PROJ_SRC)
    if proj_src_str not in sys.path:
        sys.path.insert(0, proj_src_str)

    try:
        # Force a fresh import (other tests may have loaded proj's server already).
        for key in list(sys.modules):
            if key == "server" or key.startswith("server."):
                del sys.modules[key]

        context_mod = importlib.import_module("server.tools.context")
        proj_app: FastMCP = FastMCP("proj-e2e-test")
        context_mod.register(proj_app)  # type: ignore[attr-defined]
        return proj_app
    finally:
        # Remove proj source dir from path + clear its modules so that
        # subsequent imports of ``server`` resolve to wiki's package.
        if proj_src_str in sys.path:
            sys.path.remove(proj_src_str)
        for key in list(sys.modules):
            if key == "server" or key.startswith("server."):
                del sys.modules[key]


async def test_notes_append_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """notes_append returns the documented JSON contract fields."""
    _setup_isolated_home(tmp_path, monkeypatch)
    p_app = _build_proj_app()

    contents, _meta = await p_app.call_tool("notes_append", {"text": "verify the contract"})
    payload = json.loads(contents[0].text)

    assert payload["status"] == "appended"
    assert payload["project_name"] == "test-project"
    assert payload["content"] == "verify the contract"
    assert payload["content_first_line"] == "verify the contract"
    assert "message" in payload


async def test_notes_append_to_wiki_log_manual_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling notes_append followed by wiki_log_append (the router target) writes a log entry.

    This test simulates the router hook manually: after notes_append succeeds,
    we call wiki_log_append with the param mapping the router applies
    (action="note", title=content_first_line, body=content).  The assertion
    that log.md contains the note text is the genuine cross-plugin e2e claim.
    Real router dispatch (condition evaluation, async fan-out) is covered by
    plugins/router/server/tests/.
    """
    paths = _setup_isolated_home(tmp_path, monkeypatch)
    wiki_dir: Path = paths["wiki_dir"]

    # Build proj app (clears server.* modules after registration).
    p_app = _build_proj_app()

    # Build wiki app (uses the now-clean server namespace).
    from server.tools import log as wiki_log

    w_app: FastMCP = FastMCP("wiki-e2e-test")
    wiki_log.register(w_app)

    # ── Step 1: call notes_append ─────────────────────────────────────────────
    note_text = "session summary: shipped wiki cleanup batch"
    contents, _meta = await p_app.call_tool("notes_append", {"text": note_text})
    payload = json.loads(contents[0].text)

    assert payload["status"] == "appended", f"Expected appended, got: {payload}"
    assert payload["content_first_line"] == note_text

    # ── Step 2: fire wiki_log_append with router-mapped params ────────────────
    hook_params = {
        "action": "note",
        "title": payload["content_first_line"],
        "body": payload["content"],
    }
    hook_contents, _hook_meta = await w_app.call_tool("wiki_log_append", hook_params)
    hook_payload = json.loads(hook_contents[0].text)

    # wiki_log_append returns {"entry": ..., "path": ...}
    assert "path" in hook_payload, f"Expected 'path' in response: {hook_payload}"
    # Verify the router param-mapping landed in the formatted entry directly.
    assert "entry" in hook_payload, f"Expected 'entry' in response: {hook_payload}"
    assert note_text in hook_payload["entry"], (
        f"Note title not in formatted entry: {hook_payload['entry']!r}"
    )

    # ── Step 3: assert log.md reflects the note ───────────────────────────────
    log_path = wiki_dir / "log.md"
    assert log_path.exists(), "log.md was not created"
    log_text = log_path.read_text()
    assert note_text in log_text, f"Note text not found in log.md:\n{log_text}"

    # Verify entry format: ## [YYYY-MM-DD] note | <title>
    assert re.search(
        r"## \[\d{4}-\d{2}-\d{2}\] note \| session summary: shipped wiki cleanup batch",
        log_text,
    ), f"Log entry header not found:\n{log_text}"
