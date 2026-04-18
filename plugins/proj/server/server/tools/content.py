"""MCP tools for per-todo requirements and research content."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.lib.group_tags import parent_id_from_tags
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


_MAX_PATTERN_LEN = 4096
_NESTED_QUANTIFIER_RE = re.compile(r"\([^()]*[+*]\)[+*]")
_PATTERN_TIMEOUT_S = 0.2


def _validate_pattern(pattern: str) -> tuple[re.Pattern[str] | None, str | None]:
    """Validate a regex pattern for length, nested quantifiers, and compile errors.

    Returns (compiled_pattern, None) on success or (None, error_message) on failure.
    """
    if len(pattern) > _MAX_PATTERN_LEN:
        return None, f"pattern too long: {len(pattern)} > {_MAX_PATTERN_LEN}"
    if _NESTED_QUANTIFIER_RE.search(pattern):
        return None, "pattern rejected: nested quantifier (ReDoS risk)"
    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        return None, f"invalid regex: {exc}"
    return compiled, None


def _scope_to_section(text: str, section: str) -> tuple[int, int] | None:
    """Find the character offsets of the body of the first matching section.

    Walks lines, tracking whether we are inside a fenced code block (``` or ~~~)
    to avoid matching ``#`` lines inside code fences as headings. Finds the
    first heading line whose stripped text equals ``section`` (after removing
    leading ``#`` markers and whitespace), then scans forward to the next
    heading whose ``#`` count is less than or equal to the matched heading's.
    Returns (start, end) byte offsets into ``text`` covering the section body
    (exclusive of the heading line itself). Handles section-at-EOF.
    """
    target = section.strip()
    lines = text.splitlines(keepends=True)
    in_fence = False
    fence_marker: str | None = None
    heading_re = re.compile(r"^(#+)[ \t]+(.*?)[ \t]*$")

    matched_line_idx: int | None = None
    matched_level: int | None = None

    for idx, raw in enumerate(lines):
        stripped = raw.rstrip("\r\n")
        fence_match = re.match(r"^(```|~~~)", stripped)
        if fence_match:
            if not in_fence:
                in_fence = True
                fence_marker = fence_match.group(1)
            elif fence_marker is not None and stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = None
            continue
        if in_fence:
            continue
        m = heading_re.match(stripped)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        if matched_line_idx is None:
            if title == target:
                matched_line_idx = idx
                matched_level = level
            continue
        if matched_level is not None and level <= matched_level:
            start = sum(len(line) for line in lines[: matched_line_idx + 1])
            end = sum(len(line) for line in lines[:idx])
            return (start, end)

    if matched_line_idx is None:
        return None
    start = sum(len(line) for line in lines[: matched_line_idx + 1])
    end = len(text)
    return (start, end)


def _read_utf8_strict(path: Path) -> tuple[str | None, str | None]:
    """Read a file as UTF-8 strict, preserving newlines. Returns (text, None) or (None, err)."""
    try:
        with path.open("r", encoding="utf-8", errors="strict", newline="") as f:
            return f.read(), None
    except UnicodeDecodeError as exc:
        return None, f"utf-8 decode error: {exc}"


def _atomic_write_utf8(path: Path, text: str) -> None:
    """Atomically write ``text`` to ``path`` as UTF-8, validating encoding first."""
    text.encode("utf-8", errors="strict")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _patch_content_file(
    path: Path,
    pattern: str,
    replacement: str,
    section: str | None,
    count: int,
    label: str,
) -> str:
    """Apply a regex substitution to a content file and return a JSON result."""
    if not path.exists():
        return json.dumps({"ok": False, "error": f"no {label} found"})

    text, err = _read_utf8_strict(path)
    if text is None:
        return json.dumps({"ok": False, "error": err})

    compiled, err = _validate_pattern(pattern)
    if compiled is None:
        return json.dumps({"ok": False, "error": err})

    bytes_before = len(text.encode("utf-8"))

    if section is not None:
        bounds = _scope_to_section(text, section)
        if bounds is None:
            return json.dumps({"ok": False, "error": f"section not found: {section}"})
        start, end = bounds
        scope = text[start:end]
        new_scope, n = compiled.subn(replacement, scope, count=count)
        if n == 0:
            return json.dumps({"ok": False, "error": "no match"})
        new_text = text[:start] + new_scope + text[end:]
    else:
        new_text, n = compiled.subn(replacement, text, count=count)
        if n == 0:
            return json.dumps({"ok": False, "error": "no match"})

    _atomic_write_utf8(path, new_text)
    bytes_after = len(new_text.encode("utf-8"))
    return json.dumps(
        {
            "ok": True,
            "replacements": n,
            "bytes_before": bytes_before,
            "bytes_after": bytes_after,
            "error": None,
        }
    )


def register(app: FastMCP) -> None:
    """Register content tools with the MCP app.

    Registers content_set_requirements, content_get_requirements,
    content_set_research, content_get_research, and
    proj_get_todo_context.
    """

    @app.tool(description="Write requirements.md for a todo.")
    def content_set_requirements(
        todo_id: str, content: str, project_name: str | None = None
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        storage.write_requirements(cfg, name, todo_id, content)
        return f"Written requirements.md for {todo_id}."

    @app.tool(description="Read requirements.md for a todo.")
    def content_get_requirements(
        todo_id: str, project_name: str | None = None, max_chars: int = 4000
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        result = storage.read_requirements(cfg, name, todo_id)
        if result is None:
            return f"No requirements.md found for {todo_id}."
        if len(result) > max_chars:
            file_path = storage.requirements_path(cfg, name, todo_id)
            omitted = len(result) - max_chars
            return (
                result[:max_chars]
                + f"\n\n[truncated — {omitted} chars omitted. Full file at {file_path}]"
            )
        return result

    @app.tool(description="Write research.md for a todo.")
    def content_set_research(todo_id: str, content: str, project_name: str | None = None) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        storage.write_research(cfg, name, todo_id, content)
        return f"Written research.md for {todo_id}."

    @app.tool(description="Read research.md for a todo.")
    def content_get_research(
        todo_id: str, project_name: str | None = None, max_chars: int = 4000
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        result = storage.read_research(cfg, name, todo_id)
        if result is None:
            return f"No research.md found for {todo_id}."
        if len(result) > max_chars:
            file_path = storage.research_path(cfg, name, todo_id)
            omitted = len(result) - max_chars
            return (
                result[:max_chars]
                + f"\n\n[truncated — {omitted} chars omitted. Full file at {file_path}]"
            )
        return result

    @app.tool(
        description=(
            "Return a todo's full context in one call: the todo itself, optionally its parent, "
            "requirements.md, and research.md. Replaces 3-4 separate tool calls. "
            "Returns JSON with keys: todo, parent (null if none or include_parent=false), "
            "requirements (null if not found), research (null if not found)."
        )
    )
    def proj_get_todo_context(
        todo_id: str,
        include_parent: bool = True,
        project_name: str | None = None,
        max_chars: int = 4000,
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return f"Todo '{todo_id}' not found."

        parent_dict = None
        if include_parent:
            _parent_id = parent_id_from_tags(todo.tags)
            if _parent_id:
                parent_todo = next((t for t in todos if t.id == _parent_id), None)
                if parent_todo:
                    parent_dict = parent_todo.to_dict()

        def _truncate(content: str | None, file_path: Path) -> str | None:
            if content is None:
                return None
            if len(content) > max_chars:
                omitted = len(content) - max_chars
                return (
                    content[:max_chars]
                    + f"\n\n[truncated — {omitted} chars omitted. Full file at {file_path}]"
                )
            return content

        requirements = _truncate(
            storage.read_requirements(cfg, name, todo_id),
            storage.requirements_path(cfg, name, todo_id),
        )
        research = _truncate(
            storage.read_research(cfg, name, todo_id),
            storage.research_path(cfg, name, todo_id),
        )

        return json.dumps(
            {
                "todo": todo.to_dict(),
                "parent": parent_dict,
                "requirements": requirements,
                "research": research,
            },
            indent=2,
        )

    def _patch_desc(label: str) -> str:
        return (
            f"Apply a regex substitution to {label} for a todo. Returns a JSON "
            "string with keys ok (bool), replacements (int), bytes_before (int), "
            "bytes_after (int), error (str or null). "
            "Pattern is compiled with re.MULTILINE; use ^/$ to anchor lines. "
            "If `section` is given, matching is scoped to the body of the first "
            "heading whose literal text equals `section` (first occurrence, "
            "case-sensitive, code fences respected); otherwise the whole file. "
            "`count=0` replaces all matches in the scope. Zero matches returns "
            "ok=false with error 'no match' (no write). Invalid regex (including "
            "nested-quantifier ReDoS patterns) and patterns longer than 4096 "
            "chars are rejected. File is not modified unless at least one "
            "replacement occurs. Writes are atomic."
        )

    @app.tool(description=_patch_desc("requirements.md"))
    def content_patch_requirements(
        todo_id: str,
        pattern: str,
        replacement: str,
        section: str | None = None,
        count: int = 0,
        project_name: str | None = None,
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return json.dumps({"ok": False, "error": "no active project"})
        path = storage.requirements_path(cfg, name, todo_id)
        return _patch_content_file(path, pattern, replacement, section, count, "requirements.md")

    @app.tool(description=_patch_desc("research.md"))
    def content_patch_research(
        todo_id: str,
        pattern: str,
        replacement: str,
        section: str | None = None,
        count: int = 0,
        project_name: str | None = None,
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return json.dumps({"ok": False, "error": "no active project"})
        path = storage.research_path(cfg, name, todo_id)
        return _patch_content_file(path, pattern, replacement, section, count, "research.md")
