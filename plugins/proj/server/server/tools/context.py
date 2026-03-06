"""MCP tools for session context and CLAUDE.md management."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _read_recent_notes(notes_path: Path, max_sections: int = 3, max_chars: int = 600) -> str:
    """Return last max_sections dated sections from NOTES.md, up to max_chars total."""
    if not notes_path.exists():
        return ""
    content = notes_path.read_text()
    sections = re.split(r"(?=^## \d{4}-\d{2}-\d{2})", content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]
    recent = sections[-max_sections:]  # last N sections
    result = "\n\n".join(recent)
    if len(result) > max_chars:
        result = result[-max_chars:]  # fallback tail truncation if still too long
    return result


def _format_todos_section(todos: list, lines: list[str]) -> None:
    """Append in-progress, ready, and blocked todo sections to lines."""
    open_todos = [t for t in todos if t.status not in ("done", "cancelled")]
    in_progress = [t for t in open_todos if t.status == "in_progress"]
    ready = [t for t in open_todos if t.status == "pending" and not t.blocked_by]
    blocked = [t for t in open_todos if t.blocked_by]

    if in_progress:
        lines.append(f"\n### In Progress ({len(in_progress)})")
        for t in in_progress:
            lines.append(f"- {t.id} {t.title}")
    if ready:
        lines.append(f"\n### Ready to Start ({len(ready)})")
        for t in ready[:5]:
            lines.append(f"- {t.id} {t.title}")
    if blocked:
        lines.append(f"\n### Blocked ({len(blocked)})")
        for t in blocked[:3]:
            lines.append(f"- {t.id} {t.title} (blocked by: {', '.join(t.blocked_by)})")


def _format_notes_section(cfg: object, project_name: str, lines: list[str]) -> None:
    """Append recent notes section to lines (reads NOTES.md)."""
    notes_path = storage.notes_path(cfg, project_name)
    notes = _read_recent_notes(notes_path)
    if notes:
        lines.append(f"\n### Recent Notes\n{notes}")


def _build_context(cfg: object, project_name: str, compact: bool = False) -> str:
    """Build a markdown context string for the active project."""
    from server.lib.models import ProjConfig

    assert isinstance(cfg, ProjConfig)  # noqa: S101

    meta = storage.load_meta(cfg, project_name)
    todos = storage.load_todos(cfg, project_name)

    lines = [
        f"## Active Project: {meta.name}",
        f"**Status**: {meta.status} | **Priority**: {meta.priority}",
    ]
    if meta.dates.target:
        lines.append(f"**Target**: {meta.dates.target}")
    if meta.description:
        lines.append(f"**Description**: {meta.description}")

    # Detect old single-path format
    raw = storage._load_yaml(storage.meta_path(cfg, project_name))
    if raw.get("path") and (not raw.get("repos") or raw.get("repos") == []):
        lines.append("\n⚠️ Project uses legacy single-path format. Run `/proj:migrate-dirs` to upgrade to multi-dir format.")

    _format_todos_section(todos, lines)

    if not compact:
        _format_notes_section(cfg, project_name, lines)

    return "\n".join(lines)


def register(app: FastMCP) -> None:
    """Register ctx_session_start, ctx_session_end, ctx_detect_project, notes_append, claudemd_write, and claudemd_read tools with the MCP app."""

    @app.tool(description="Build session context string for active project (SessionStart hook).")
    def ctx_session_start(cwd: str | None = None, compact: bool = False) -> str:
        if not storage.config_exists():
            return ""
        cfg = storage.load_config()

        # Session override takes precedence
        session_override = state.get_session_active()
        if session_override:
            index = storage.load_index(cfg)
            if session_override in index.projects:
                try:
                    return _build_context(cfg, session_override, compact=compact)
                except FileNotFoundError:
                    pass

        # Auto-detect from cwd (session-only, not persisted)
        if cwd:
            project_name = ctx_detect_project_name(cwd)
            if project_name:
                state.set_session_active(project_name)
                try:
                    return _build_context(cfg, project_name, compact=compact)
                except FileNotFoundError:
                    pass

        return ""

    @app.tool(description="Update last_updated timestamp for the active project (SessionEnd hook).")
    def ctx_session_end(cwd: str | None = None) -> str:
        if not storage.config_exists():
            return "No config."
        cfg = storage.load_config()
        name = state.get_session_active()
        if not name:
            return "No active project."
        try:
            meta = storage.load_meta(cfg, name)
            storage.save_meta(cfg, meta)  # save_meta bumps last_updated
            return f"Updated last_updated for '{name}'."
        except FileNotFoundError:
            return "Project not found."

    @app.tool(description="Detect which tracked project matches the given cwd.")
    def ctx_detect_project(cwd: str) -> str:
        if not storage.config_exists():
            return "No config."
        name = ctx_detect_project_name(cwd)
        return name if name else "No project matched."

    @app.tool(description="Append a dated note to the active project's NOTES.md.")
    def notes_append(text: str, project_name: str | None = None) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        storage.append_note(cfg, name, text)
        return f"Note appended to {name}/NOTES.md."

    @app.tool(description="Write or update CLAUDE.md in a project repo directory.")
    def claudemd_write(repo_path: str, content: str) -> str:
        cfg = require_config()
        # Resolve effective claudemd_management flag (project overrides global)
        proj_name = ctx_detect_project_name(repo_path)
        enabled = cfg.claudemd_management  # global default
        if proj_name:
            meta = storage.load_meta(cfg, proj_name)
            if meta.claudemd_management is not None:
                enabled = meta.claudemd_management
        if not enabled:
            return "CLAUDE.md management is disabled (claudemd_management=false). Enable it in global or project config to allow writes."
        storage.write_claudemd(repo_path, content)
        return f"Written CLAUDE.md at {repo_path}."

    @app.tool(description="Read CLAUDE.md from a project repo directory.")
    def claudemd_read(repo_path: str) -> str:
        result = storage.read_claudemd(repo_path)
        return result if result is not None else f"No CLAUDE.md found at {repo_path}."


def ctx_detect_project_name(cwd: str) -> str | None:
    """Return the project name that matches cwd, or None."""
    if not storage.config_exists():
        return None
    cfg = storage.load_config()
    index = storage.load_index(cfg)
    cwd_path = Path(cwd).resolve()
    for name, entry in index.projects.items():
        if entry.archived:
            continue
        try:
            meta = storage.load_meta(cfg, name)
            for repo in meta.repos:
                repo_path = Path(repo.path).resolve()
                if cwd_path == repo_path or cwd_path.is_relative_to(repo_path):
                    return name
        except FileNotFoundError:
            continue
    return None
