"""MCP tools for session context and CLAUDE.md management."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.enums import TERMINAL_STATUSES
from server.tools.config import require_config
from server.tools.context_injection import inject_context
from server.tools.git import _active_branches, _git_log

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.lib.models import JsonValue, ProjConfig, ProjectMeta, Todo

logger = logging.getLogger(__name__)


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


def _format_todos_section(todos: list[Todo], lines: list[str]) -> None:
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


def _format_notes_section(cfg: ProjConfig, project_name: str, lines: list[str]) -> None:
    """Append recent notes section to lines (reads NOTES.md)."""
    notes_path = storage.notes_path(cfg, project_name)
    notes = _read_recent_notes(notes_path)
    if notes:
        lines.append(f"\n### Recent Notes\n{notes}")


def _read_session_history(cfg: ProjConfig, project_name: str) -> dict[str, JsonValue]:
    """Return session history data from recent session files.

    Returns a dict with:
      - summary: first 300 chars of the latest session file (after ``# Session:`` header)
      - decisions: last 5 Key Decisions across recent sessions (deduplicated)
      - questions: unresolved questions from last 3 sessions
    """
    sessions_dir = storage.tracking_dir(cfg, project_name) / "sessions"
    if not sessions_dir.is_dir():
        return {}

    files = sorted(sessions_dir.glob("session-*.md"))
    if not files:
        return {}

    # --- summary from latest session ---
    latest_content = files[-1].read_text()
    # Strip the ``# Session: ...`` header line
    header_match = re.match(r"^# Session:[^\n]*\n?", latest_content)
    body = latest_content[header_match.end() :] if header_match else latest_content
    summary = body.strip()[:300]

    # --- decisions from recent sessions (last 5 decisions, deduplicated) ---
    decisions: list[str] = []
    seen_decisions: set[str] = set()
    for f in reversed(files):
        content = f.read_text()
        sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
        for section in sections:
            if section.startswith("## Key Decisions"):
                for line in section.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        item = stripped[2:].strip()
                        if item not in seen_decisions:
                            seen_decisions.add(item)
                            decisions.append(item)
        if len(decisions) >= 5:
            break
    decisions = decisions[:5]

    # --- open questions from last 3 sessions ---
    questions: list[str] = []
    recent_files = files[-3:]
    for f in recent_files:
        content = f.read_text()
        sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
        for section in sections:
            if section.startswith("## Open Questions"):
                for line in section.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        item = stripped[2:].strip()
                        if item not in questions:
                            questions.append(item)

    return {"summary": summary, "decisions": decisions, "questions": questions}


def _format_session_history(cfg: ProjConfig, project_name: str, lines: list[str]) -> None:
    """Append session history sections to *lines* if session data exists."""
    data = _read_session_history(cfg, project_name)
    if not data:
        return

    summary = data.get("summary", "")
    decisions_raw = data.get("decisions", [])
    decisions: list[str] = (
        [str(d) for d in decisions_raw] if isinstance(decisions_raw, list) else []
    )
    questions_raw = data.get("questions", [])
    questions: list[str] = (
        [str(q) for q in questions_raw] if isinstance(questions_raw, list) else []
    )

    if summary:
        lines.append(f"\n### Last Session\n{summary}")

    if decisions:
        lines.append(f"\n### Key Decisions (last {len(decisions)})")
        for d in decisions:
            lines.append(f"- {d}")

    if questions:
        lines.append("\n### Open Questions")
        for q in questions:
            lines.append(f"- [ ] {q}")


def _read_project_knowledge(cfg: ProjConfig, project_name: str, max_bullets: int = 5) -> list[str]:
    """Return up to *max_bullets* bullet entries from the most recent section of knowledge.md."""
    knowledge_path = storage.tracking_dir(cfg, project_name) / "knowledge.md"
    if not knowledge_path.exists():
        return []
    content = knowledge_path.read_text()
    # Split into dated sections (## YYYY-MM-DD)
    sections = re.split(r"(?=^## \d{4}-\d{2}-\d{2})", content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]
    if not sections:
        return []
    # Take the last (most recent) section
    latest = sections[-1]
    bullets: list[str] = []
    for line in latest.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
            if len(bullets) >= max_bullets:
                break
    return bullets


def _format_knowledge_section(cfg: ProjConfig, project_name: str, lines: list[str]) -> None:
    """Append project knowledge section to *lines* if knowledge.md exists."""
    bullets = _read_project_knowledge(cfg, project_name)
    if bullets:
        lines.append("\n### Project Knowledge")
        for b in bullets:
            lines.append(f"- {b}")


def _collect_git_diff_paths(meta: ProjectMeta) -> list[str]:
    """Collect changed file paths from git diff across all trackable repos.

    Runs ``git diff --name-only`` and ``git diff --cached --name-only`` per repo.
    Returns empty list on any failure (timeout, subprocess error, etc.).
    """
    paths: list[str] = []
    trackable_repos = [repo for repo in meta.repos if not repo.reference]
    for repo in trackable_repos:
        try:
            for cmd in (
                ["git", "diff", "--name-only"],
                ["git", "diff", "--cached", "--name-only"],
            ):
                result = subprocess.run(
                    cmd,
                    cwd=repo.path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().splitlines():
                        if line:
                            paths.append(line)
        except Exception:
            logger.debug("Failed to list worktree paths", exc_info=True)
    return paths


def _build_context(cfg: ProjConfig, project_name: str, compact: bool = False) -> str:
    """Build a markdown context string for the active project."""
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
        lines.append(
            "\n⚠️ Project uses legacy single-path format."
            " Run `/proj:migrate-dirs` to upgrade to multi-dir format."
        )

    _format_todos_section(todos, lines)

    if not compact:
        if cfg.context_injection.enabled:
            try:
                git_paths = _collect_git_diff_paths(meta)
                result = inject_context(cfg, project_name, todos, git_paths)
                if result.notes:
                    lines.append(f"\n### Recent Notes\n{result.notes}")
                if result.decisions:
                    lines.append(f"\n### Key Decisions\n{result.decisions}")
                if result.knowledge:
                    lines.append(f"\n### Project Knowledge\n{result.knowledge}")
            except Exception:
                logger.warning("context_injection failed, falling back to legacy", exc_info=True)
                _format_notes_section(cfg, project_name, lines)
                _format_knowledge_section(cfg, project_name, lines)
            # Session history is always appended (not handled by context injection)
            _format_session_history(cfg, project_name, lines)
        else:
            _format_notes_section(cfg, project_name, lines)
            _format_session_history(cfg, project_name, lines)
            _format_knowledge_section(cfg, project_name, lines)

    return "\n".join(lines)


def register(app: FastMCP) -> None:
    """Register context tools with the MCP app.

    Registers ctx_session_start, ctx_session_end, ctx_detect_project,
    notes_append, claudemd_write, claudemd_read, proj_session_context,
    and proj_status_context.
    """

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
            return (
                "CLAUDE.md management is disabled"
                " (claudemd_management=false). Enable it in global"
                " or project config to allow writes."
            )
        storage.write_claudemd(repo_path, content)
        return f"Written CLAUDE.md at {repo_path}."

    @app.tool(description="Read CLAUDE.md from a project repo directory.")
    def claudemd_read(repo_path: str) -> str:
        result = storage.read_claudemd(repo_path)
        return result if result is not None else f"No CLAUDE.md found at {repo_path}."

    @app.tool(
        description=(
            "Return structured JSON context for the active project"
            " session (config, project metadata, integrations)."
        )
    )
    def proj_session_context(include_todo_count: bool = False) -> str:
        if not storage.config_exists():
            return "No config found. Run config_init first."
        cfg = require_config()
        project_name = state.resolve_project(None)
        if not project_name:
            return "No active project. Use ctx_session_start or proj_set_active first."
        try:
            meta = storage.load_meta(cfg, project_name)
        except FileNotFoundError:
            return f"Project metadata not found for '{project_name}'."

        result: dict[str, JsonValue] = {
            "config": {
                "tracking_dir": cfg.tracking_dir,
                "projects_base_dir": cfg.projects_base_dir,
                "default_priority": cfg.default_priority,
            },
            "project": {
                "name": meta.name,
                "status": meta.status,
                "priority": meta.priority,
                "description": meta.description,
                "repos": [r.to_dict() for r in meta.repos],
                "tags": meta.tags,
                "todoist_project_id": meta.todoist_project_id,
                "trello_card_id": meta.trello_card_id,
            },
            "integrations": {
                "todoist": {
                    "enabled": cfg.todoist.enabled,
                    "mcp_server": cfg.todoist.mcp_server,
                    "project_id": meta.todoist_project_id,
                },
                "trello": {
                    "enabled": cfg.trello.enabled,
                    "board_id": cfg.trello.default_board_id,
                    "card_id": meta.trello_card_id,
                    # Surface label names as-is (including empty strings) so
                    # preflight can distinguish absent (default applies) from
                    # explicitly-set-to-empty (trello-setup errors).
                    "proj_label_name": cfg.trello.proj_label_name,
                    "proj_task_label_name": cfg.trello.proj_task_label_name,
                },
                "jira": {
                    "enabled": cfg.jira.enabled,
                },
                "worktree": {
                    "enabled": cfg.worktree_integration,
                },
                "zoxide": {
                    "enabled": cfg.zoxide_integration,
                },
            },
        }

        if include_todo_count:
            todos = storage.load_todos(cfg, project_name)
            open_todos = [t for t in todos if t.status not in ("done", "cancelled")]
            result["todo_count"] = {
                "total": len(todos),
                "open": len(open_todos),
                "in_progress": len([t for t in open_todos if t.status == "in_progress"]),
                "pending": len([t for t in open_todos if t.status == "pending"]),
            }

        return json.dumps(result)

    @app.tool(
        description=(
            "Return structured JSON context for the status skill:"
            " config, project metadata, categorised todos, and"
            " git activity in one call."
        )
    )
    def proj_status_context(project_name: str | None = None) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project. Use ctx_session_start or proj_set_active first."
        try:
            meta = storage.load_meta(cfg, name)
        except FileNotFoundError:
            return f"Project metadata not found for '{name}'."

        todos = storage.load_todos(cfg, name)

        # Categorise todos
        in_progress = [t for t in todos if t.status == "in_progress"]
        all_open = [t for t in todos if t.status not in TERMINAL_STATUSES]
        ready = [t for t in all_open if not t.blocked_by and t.status != "in_progress"]
        blocked = [t for t in all_open if t.blocked_by]
        done_count = sum(1 for t in todos if t.status == "done")

        def _todo_summary(t: Todo) -> dict[str, JsonValue]:
            return {
                "id": t.id,
                "title": t.title,
                "priority": t.priority,
                "status": t.status,
                "tags": t.tags,
                "blocked_by": t.blocked_by,
                "children_count": len(t.children),
            }

        # Git activity
        git_activity: dict[str, JsonValue] = {"git_enabled": False, "commits": [], "branches": []}
        if meta.git_enabled:
            all_commits: list[str] = []
            all_branches: list[str] = []
            trackable_repos = [repo for repo in meta.repos if not repo.reference]
            with ThreadPoolExecutor() as executor:
                log_futures = {
                    executor.submit(_git_log, repo.path, 7, repo.label): repo
                    for repo in trackable_repos
                }
                branch_futures = {
                    executor.submit(_active_branches, repo.path): repo for repo in trackable_repos
                }
                for fut, _repo in log_futures.items():
                    all_commits.extend(fut.result())
                for fut, repo in branch_futures.items():
                    all_branches.extend(f"{repo.label}:{b}" for b in fut.result())
            git_activity = {"git_enabled": True, "commits": all_commits, "branches": all_branches}

        result: dict[str, JsonValue] = {
            "config": {
                "tracking_dir": cfg.tracking_dir,
                "projects_base_dir": cfg.projects_base_dir,
            },
            "project": {
                "name": meta.name,
                "status": meta.status,
                "priority": meta.priority,
                "description": meta.description,
                "repos": [r.to_dict() for r in meta.repos],
                "tags": meta.tags,
                "dates": meta.dates.to_dict(),
            },
            "todos": {
                "in_progress": [_todo_summary(t) for t in in_progress],
                "ready": [_todo_summary(t) for t in ready],
                "blocked": [_todo_summary(t) for t in blocked],
                "all_open": [_todo_summary(t) for t in all_open],
                "done_count": done_count,
            },
            "git_activity": git_activity,
        }

        return json.dumps(result)


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
