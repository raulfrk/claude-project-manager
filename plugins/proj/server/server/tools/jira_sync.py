"""MCP tools for Jira sync — map and apply."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import TYPE_CHECKING, Any

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import Todo
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# ── Priority mapping ─────────────────────────────────────────────────────────

_JIRA_TO_LOCAL: dict[str, str] = {
    "critical": "high",
    "highest": "high",
    "high": "medium",
    "medium": "medium",
    "low": "low",
    "lowest": "low",
}


_UTC = timezone.utc


def _now() -> str:
    """Return current UTC datetime as ISO 8601 string for time precision."""
    return datetime.now(tz=_UTC).replace(tzinfo=None).isoformat()


def _today() -> str:
    return str(date.today())


def _slugify(name: str) -> str:
    """Convert a name to a slug suitable for project names."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"


def _parse_jira_priority(issue: dict[str, Any]) -> str:
    """Map Jira priority to local priority string."""
    priority_raw = issue.get("priority")
    if isinstance(priority_raw, dict):
        name = str(priority_raw.get("name", "")).lower()
    elif isinstance(priority_raw, str):
        name = priority_raw.lower()
    else:
        return "medium"
    return _JIRA_TO_LOCAL.get(name, "medium")


def _parse_jira_status(issue: dict[str, Any]) -> str:
    """Extract status name from Jira issue."""
    status_raw = issue.get("status")
    if isinstance(status_raw, dict):
        return str(status_raw.get("name", ""))
    if isinstance(status_raw, str):
        return status_raw
    return ""


def _is_resolved(issue: dict[str, Any]) -> bool:
    """Check if a Jira issue is in a resolved/done state."""
    status = _parse_jira_status(issue).lower()
    return status in {"done", "resolved", "closed", "cancelled", "canceled"}


def _parse_jira_labels(issue: dict[str, Any]) -> list[str]:
    """Extract labels list from Jira issue."""
    labels = issue.get("labels")
    return [str(x) for x in labels] if isinstance(labels, list) else []


def _parse_jira_duedate(issue: dict[str, Any]) -> str | None:
    """Extract due date from Jira issue."""
    raw = issue.get("duedate")
    if isinstance(raw, str) and raw:
        return raw[:10]  # YYYY-MM-DD
    return None


def _fuzzy_match_project(name: str, project_names: list[str], threshold: float = 0.6) -> str | None:
    """Find a fuzzy match for a name in existing project names."""
    lower_name = name.lower()
    # Exact match first
    for pn in project_names:
        if pn.lower() == lower_name:
            return pn
    # Slug match
    slug = _slugify(name)
    for pn in project_names:
        if _slugify(pn) == slug:
            return pn
    # Fuzzy match
    matches = difflib.get_close_matches(name.lower(), [p.lower() for p in project_names], n=1, cutoff=threshold)
    if matches:
        # Find the original-case name
        for pn in project_names:
            if pn.lower() == matches[0]:
                return pn
    return None


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class JiraGroup:
    """A group of Jira issues organized by epic or standalone."""

    source: str  # "epic" or "standalone"
    jira_key: str  # Epic key or individual issue key
    name: str  # Epic name or issue summary
    suggested_project: str  # Slugified project name or "" if unmapped
    is_epic: bool = False
    needs_user_decision: bool = False  # True when no auto-match possible
    project_exists: bool = False
    matched_project: str | None = None  # Name of matched local project
    issues: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "source": self.source,
            "jira_key": self.jira_key,
            "name": self.name,
            "suggested_project": self.suggested_project,
            "is_epic": self.is_epic,
            "needs_user_decision": self.needs_user_decision,
            "project_exists": self.project_exists,
            "issues": self.issues,
        }
        if self.matched_project:
            d["matched_project"] = self.matched_project
        return d


@dataclass
class JiraMappingPlan:
    """Result of mapping Jira issues to local projects."""

    groups: list[JiraGroup] = field(default_factory=list)
    total_issues: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "total_issues": self.total_issues,
            "summary": {
                "total_issues": self.total_issues,
                "group_count": len(self.groups),
                "auto_mapped_count": sum(1 for g in self.groups if not g.needs_user_decision),
                "needs_input_count": sum(1 for g in self.groups if g.needs_user_decision),
                "needs_input_groups": [
                    {"jira_key": g.jira_key, "name": g.name, "issue_count": len(g.issues)}
                    for g in self.groups if g.needs_user_decision
                ],
            },
        }


@dataclass
class JiraApplyInput:
    """Input for applying Jira mapping to local projects."""

    groups: list[dict[str, Any]] = field(default_factory=list)


# ── Notes formatting ──────────────────────────────────────────────────────────


def _format_jira_notes(issue_key: str, description: str) -> str:
    """Build the Jira section of a todo's notes from a description."""
    lines = [f"## Jira: {issue_key}", "### Description", description.strip()]
    return "\n".join(lines)


def _append_jira_comments(
    todo: Todo,
    comments: list[dict[str, Any]],
) -> None:
    """Append new Jira comments to *todo.notes*, deduplicating by comment ID.

    Each comment dict is expected to have ``id``, ``author`` (str or dict with
    ``displayName``), ``created`` (ISO date string), and ``body`` keys.
    Already-synced IDs stored in ``todo.jira_synced_comment_ids`` are skipped.
    """
    existing_ids = set(todo.jira_synced_comment_ids)
    new_parts: list[str] = []
    new_ids: list[str] = []

    for comment in comments:
        cid = str(comment.get("id", ""))
        if not cid or cid in existing_ids:
            continue
        author_raw = comment.get("author")
        if isinstance(author_raw, dict):
            author = str(author_raw.get("displayName", "") or author_raw.get("name", ""))
        elif isinstance(author_raw, str):
            author = author_raw
        else:
            author = "Unknown"
        created = str(comment.get("created", ""))[:10]  # YYYY-MM-DD
        body = str(comment.get("body", "")).strip()
        new_parts.append(f"**{author}** ({created}): {body}")
        new_ids.append(cid)

    if not new_parts:
        return

    # If notes already contain a ### Comments section, append after it;
    # otherwise add the header first.
    comments_header = "### Comments"
    if comments_header not in todo.notes:
        todo.notes = todo.notes.rstrip() + "\n" + comments_header if todo.notes.strip() else comments_header
    todo.notes = todo.notes.rstrip() + "\n" + "\n".join(new_parts)
    todo.jira_synced_comment_ids.extend(new_ids)


def _sync_root_issue_to_notes(
    cfg: Any,
    project_name: str,
    meta: Any,
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
) -> None:
    """Sync the root Jira issue (1:1 with project) to NOTES.md instead of a todo.

    Appends description (under ``## Jira: <key>``) and new comments, deduplicating
    by checking the existing NOTES.md content for the header and using
    ``meta.jira_synced_comment_ids`` for comment-level dedup.
    """
    issue_key = str(issue.get("key", ""))
    description = str(issue.get("description", "") or "").strip()

    notes_file = storage.notes_path(cfg, project_name)
    existing = notes_file.read_text() if notes_file.exists() else ""

    jira_header = f"## Jira: {issue_key}"
    parts: list[str] = []

    # Append description block if not already present
    if description and jira_header not in existing:
        parts.append(f"{jira_header}\n### Description\n{description}")

    # Append only new comments (dedup by ID)
    existing_ids = set(meta.jira_synced_comment_ids)
    new_comment_lines: list[str] = []
    new_ids: list[str] = []
    for comment in comments:
        cid = str(comment.get("id", ""))
        if not cid or cid in existing_ids:
            continue
        author_raw = comment.get("author")
        if isinstance(author_raw, dict):
            author = str(author_raw.get("displayName", "") or author_raw.get("name", ""))
        elif isinstance(author_raw, str):
            author = author_raw
        else:
            author = "Unknown"
        created = str(comment.get("created", ""))[:10]
        body = str(comment.get("body", "")).strip()
        new_comment_lines.append(f"**{author}** ({created}): {body}")
        new_ids.append(cid)

    if new_comment_lines:
        # Add ### Comments header if not yet in the file
        if "### Comments" not in existing and "### Comments" not in "\n".join(parts):
            parts.append("### Comments")
        parts.append("\n".join(new_comment_lines))

    if parts:
        block = "\n".join(parts)
        notes_file.parent.mkdir(parents=True, exist_ok=True)
        if existing and not existing.endswith("\n"):
            existing += "\n"
        notes_file.write_text(existing + block + "\n")

    if new_ids:
        meta.jira_synced_comment_ids.extend(new_ids)


# ── Core logic (standalone functions) ─────────────────────────────────────────


def _build_issue_entry(issue: dict[str, Any]) -> dict[str, object]:
    """Extract a normalised issue entry dict from a raw Jira issue."""
    issue_key = str(issue.get("key", ""))
    summary = str(issue.get("summary", ""))
    priority = _parse_jira_priority(issue)
    status = _parse_jira_status(issue)
    labels = _parse_jira_labels(issue)
    duedate = _parse_jira_duedate(issue)
    description = str(issue.get("description", "") or "")
    assignee_raw = issue.get("assignee")
    assignee = ""
    if isinstance(assignee_raw, dict):
        assignee = str(assignee_raw.get("displayName", "") or assignee_raw.get("name", ""))
    elif isinstance(assignee_raw, str):
        assignee = assignee_raw

    subtasks_raw = issue.get("subtasks", [])
    subtasks: list[dict[str, object]] = []
    if isinstance(subtasks_raw, list):
        for st in subtasks_raw:
            if isinstance(st, dict):
                subtasks.append({
                    "key": str(st.get("key", "")),
                    "summary": str(st.get("summary", "") or str(st.get("fields", {}).get("summary", ""))),
                    "status": _parse_jira_status(st.get("fields", st) if isinstance(st.get("fields"), dict) else st),
                })

    entry: dict[str, object] = {
        "key": issue_key,
        "summary": summary,
        "priority": priority,
        "status": status,
        "labels": labels,
        "description": description,
    }
    if duedate:
        entry["duedate"] = duedate
    if assignee:
        entry["assignee"] = assignee
    if subtasks:
        entry["subtasks"] = subtasks
    return entry


def _detect_epic_key(issue: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (epic_key, epic_name) for an issue, or (None, None)."""
    # Check if the issue itself is an Epic
    issuetype = issue.get("issuetype")
    if isinstance(issuetype, dict) and str(issuetype.get("name", "")).lower() == "epic":
        return str(issue.get("key", "")), str(issue.get("summary", ""))
    fields = issue.get("fields")
    if isinstance(fields, dict):
        ft = fields.get("issuetype")
        if isinstance(ft, dict) and str(ft.get("name", "")).lower() == "epic":
            return str(issue.get("key", "")), str(fields.get("summary", issue.get("summary", "")))

    # Check parent reference for epic link
    parent = issue.get("parent")
    if isinstance(parent, dict):
        parent_fields = parent.get("fields", {})
        if isinstance(parent_fields, dict):
            pt = parent_fields.get("issuetype", {})
            if isinstance(pt, dict) and str(pt.get("name", "")).lower() == "epic":
                return str(parent.get("key", "")), str(parent_fields.get("summary", parent.get("key", "")))

    return None, None


def _is_epic_issue(issue: dict[str, Any]) -> bool:
    """Return True if the issue itself is an Epic (not just linked to one)."""
    issuetype = issue.get("issuetype")
    if isinstance(issuetype, dict) and str(issuetype.get("name", "")).lower() == "epic":
        return True
    fields = issue.get("fields")
    if isinstance(fields, dict):
        ft = fields.get("issuetype")
        if isinstance(ft, dict) and str(ft.get("name", "")).lower() == "epic":
            return True
    return False


def _match_by_jira_key(jira_key: str, cfg: Any, existing_names: list[str]) -> str | None:
    """Look up an existing project by its jira_issue_key metadata field."""
    for name in existing_names:
        try:
            meta = storage.load_meta(cfg, name)
            if meta.jira_issue_key == jira_key:
                return name
        except FileNotFoundError:
            continue
    return None


def compute_mapping(
    jira_issues: list[dict[str, Any]],
    cfg: Any,
    project_name: str | None = None,
) -> JiraMappingPlan:
    """Group Jira issues by epic (epic-first) and map to local projects.

    Logic:
    1. Separate epics from non-epics
    2. For each epic: create JiraGroup with is_epic=True, child issues as sub-items
    3. For non-epic with epic parent: add to that epic's group
    4. For issues with no epic: create standalone group with needs_user_decision=True
    5. Match against existing projects by jira_issue_key first, then fuzzy name
    6. No catchall/default project — unmapped issues stay as "unmapped"
    """
    index = storage.load_index(cfg)
    existing_names = [
        name for name, entry in index.projects.items()
        if not entry.archived
    ]

    # Phase 1: separate epics and collect epic metadata
    epic_groups: dict[str, JiraGroup] = {}  # epic_key -> group
    non_epic_issues: list[dict[str, Any]] = []

    for issue in jira_issues:
        if _is_epic_issue(issue):
            epic_key = str(issue.get("key", ""))
            epic_name = str(issue.get("summary", ""))
            if not epic_key:
                continue
            if epic_key not in epic_groups:
                # Match: jira_issue_key on project first, then fuzzy name
                if project_name:
                    matched = project_name
                else:
                    matched = _match_by_jira_key(epic_key, cfg, existing_names)
                    if matched is None:
                        matched = _fuzzy_match_project(epic_name, existing_names)
                slug = _slugify(epic_name)
                epic_groups[epic_key] = JiraGroup(
                    source="epic",
                    jira_key=epic_key,
                    name=epic_name,
                    suggested_project=matched or slug,
                    is_epic=True,
                    needs_user_decision=False,
                    project_exists=matched is not None,
                    matched_project=matched,
                )
            # Epic issues themselves are NOT added as sub-items (they become the project)
        else:
            non_epic_issues.append(issue)

    # Phase 2: assign non-epic issues to epic groups or standalone
    standalone_issues: list[tuple[dict[str, Any], dict[str, object]]] = []

    for issue in non_epic_issues:
        issue_entry = _build_issue_entry(issue)
        epic_key, epic_name = _detect_epic_key(issue)

        if epic_key and epic_key in epic_groups:
            # Parent epic already known
            epic_groups[epic_key].issues.append(issue_entry)
        elif epic_key and epic_name:
            # Epic not in our issues list but referenced — create group
            if project_name:
                matched = project_name
            else:
                matched = _match_by_jira_key(epic_key, cfg, existing_names)
                if matched is None:
                    matched = _fuzzy_match_project(epic_name, existing_names)
            slug = _slugify(epic_name)
            epic_groups[epic_key] = JiraGroup(
                source="epic",
                jira_key=epic_key,
                name=epic_name,
                suggested_project=matched or slug,
                is_epic=True,
                needs_user_decision=False,
                project_exists=matched is not None,
                matched_project=matched,
            )
            epic_groups[epic_key].issues.append(issue_entry)
        else:
            # No epic — standalone
            standalone_issues.append((issue, issue_entry))

    # Phase 3: create standalone groups (needs_user_decision=True, no catchall)
    standalone_groups: list[JiraGroup] = []
    for issue, issue_entry in standalone_issues:
        issue_key = str(issue.get("key", ""))
        summary = str(issue.get("summary", ""))
        # Try jira_issue_key match on project, then fuzzy name
        if project_name:
            matched = project_name
        else:
            matched = _match_by_jira_key(issue_key, cfg, existing_names)
            if matched is None:
                matched = _fuzzy_match_project(summary, existing_names)
        slug = _slugify(summary)
        standalone_groups.append(JiraGroup(
            source="standalone",
            jira_key=issue_key,
            name=summary,
            suggested_project=matched or "",
            is_epic=False,
            needs_user_decision=matched is None,
            project_exists=matched is not None,
            matched_project=matched,
            issues=[issue_entry],
        ))

    plan = JiraMappingPlan()
    plan.groups = list(epic_groups.values()) + standalone_groups
    plan.total_issues = len(jira_issues)
    return plan


def apply_mapping(
    data: JiraApplyInput,
    cfg: Any,
    comments_by_key: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, int]:
    """Apply confirmed Jira mapping to local projects. Returns counts dict.

    When creating a project from an epic group, sets jira_issue_key on the
    ProjectMeta so that re-runs can instantly match the epic to the project.
    Groups with no suggested_project (unmapped) are skipped.

    *comments_by_key* maps issue keys to lists of Jira comment dicts.
    Each comment dict should have ``id``, ``author``, ``created``, ``body``.
    """
    if comments_by_key is None:
        comments_by_key = {}
    today = _now()
    counts = {
        "projects_created": 0,
        "todos_created": 0,
        "todos_updated": 0,
        "skipped_unmapped": 0,
    }

    for group in data.groups:
        project_name = str(group.get("suggested_project", ""))
        if not project_name:
            counts["skipped_unmapped"] += len(group.get("issues", []))
            continue

        create_project = group.get("create_project", False)
        project_exists = group.get("project_exists", False)
        is_epic = group.get("is_epic", False)
        jira_key = str(group.get("jira_key", ""))

        # Create project if needed
        if create_project and not project_exists:
            proj_dir = storage.tracking_dir(cfg, project_name)
            proj_dir.mkdir(parents=True, exist_ok=True)
            from server.lib.models import ProjectDates, ProjectEntry, ProjectMeta

            meta = ProjectMeta(
                name=project_name,
                description=str(group.get("name", "")),
                dates=ProjectDates(created=today, last_updated=today),
                # Link project to epic for instant re-run matching
                jira_issue_key=jira_key if is_epic else None,
            )
            storage.save_meta(cfg, meta)
            (proj_dir / "todos.yaml").write_text("todos: []\n")
            (proj_dir / "archive.yaml").write_text("todos: []\n")

            # Add to index
            index = storage.load_index(cfg)
            index.projects[project_name] = ProjectEntry(
                name=project_name,
                tracking_dir=str(proj_dir),
                created=today,
            )
            storage.save_index(cfg, index)
            counts["projects_created"] += 1

            # Append epic description/comments to project NOTES.md
            if is_epic:
                epic_desc = str(group.get("description", "") or "")
                note_parts: list[str] = []
                if epic_desc:
                    note_parts.append(f"## Jira: {jira_key}\n### Description\n{epic_desc.strip()}")
                epic_comments = comments_by_key.get(jira_key, [])
                if epic_comments:
                    comment_lines: list[str] = []
                    for ec in epic_comments:
                        ec_author_raw = ec.get("author")
                        if isinstance(ec_author_raw, dict):
                            ec_author = str(ec_author_raw.get("displayName", "") or ec_author_raw.get("name", ""))
                        elif isinstance(ec_author_raw, str):
                            ec_author = ec_author_raw
                        else:
                            ec_author = "Unknown"
                        ec_created = str(ec.get("created", ""))[:10]
                        ec_body = str(ec.get("body", "")).strip()
                        comment_lines.append(f"**{ec_author}** ({ec_created}): {ec_body}")
                    note_parts.append("### Comments\n" + "\n".join(comment_lines))
                if note_parts:
                    storage.append_note(cfg, project_name, "\n".join(note_parts))
                # Track epic comment IDs on meta to avoid duplicates on re-sync
                if epic_comments:
                    meta.jira_synced_comment_ids = [str(ec.get("id", "")) for ec in epic_comments if ec.get("id")]
                    storage.save_meta(cfg, meta)

        # Process issues
        issues = group.get("issues", [])
        if not isinstance(issues, list):
            continue

        try:
            meta = storage.load_meta(cfg, project_name)
        except FileNotFoundError:
            continue

        # On re-run with existing epic project: ensure jira_issue_key is set
        if is_epic and jira_key and not meta.jira_issue_key:
            meta.jira_issue_key = jira_key

        todos = storage.load_todos(cfg, project_name)
        todo_map = {t.id: t for t in todos}

        # Build lookup by jira_issue_key
        by_jira_key: dict[str, Todo] = {}
        for todo in todos:
            if todo.jira_issue_key:
                by_jira_key[todo.jira_issue_key] = todo

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_key = str(issue.get("key", ""))
            if not issue_key:
                continue

            if issue_key == meta.jira_issue_key:
                # Root issue -> NOTES.md, not a todo
                _sync_root_issue_to_notes(cfg, project_name, meta, issue, comments_by_key.get(issue_key, []))
                continue

            summary = str(issue.get("summary", ""))
            priority = str(issue.get("priority", "medium"))
            status = str(issue.get("status", ""))
            labels = issue.get("labels", [])
            labels = [str(x) for x in labels] if isinstance(labels, list) else []
            description = str(issue.get("description", "") or "")
            duedate = str(issue.get("duedate", "")) if issue.get("duedate") else None
            resolved = status.lower() in {"done", "resolved", "closed", "cancelled", "canceled"}

            # Format description into structured notes
            formatted_notes = _format_jira_notes(issue_key, description) if description else ""

            if issue_key in by_jira_key:
                # Update existing todo
                todo = by_jira_key[issue_key]
                todo.title = summary
                todo.priority = priority
                todo.tags = labels
                if formatted_notes and formatted_notes != todo.notes:
                    # Preserve any ### Comments section already appended
                    comments_marker = "### Comments"
                    if comments_marker in todo.notes:
                        idx = todo.notes.index(comments_marker)
                        todo.notes = formatted_notes.rstrip() + "\n" + todo.notes[idx:]
                    else:
                        todo.notes = formatted_notes
                if duedate:
                    todo.due_date = duedate
                if resolved and todo.status not in TERMINAL_STATUSES:
                    todo.status = TodoStatus.DONE
                todo.updated = today
                counts["todos_updated"] += 1
            else:
                # Create new todo
                todo = Todo(
                    id=next_todo_id(meta),
                    title=summary,
                    priority=priority,
                    tags=labels,
                    notes=formatted_notes,
                    due_date=duedate,
                    jira_issue_key=issue_key,
                    status=TodoStatus.DONE if resolved else "pending",
                    created=today,
                    updated=today,
                )
                todos.append(todo)
                todo_map[todo.id] = todo
                by_jira_key[issue_key] = todo
                counts["todos_created"] += 1

            # Append Jira comments (deduped by comment ID)
            issue_comments = comments_by_key.get(issue_key, [])
            if issue_comments:
                _append_jira_comments(todo, issue_comments)

            # Handle subtasks
            subtasks = issue.get("subtasks", [])
            if isinstance(subtasks, list):
                for st in subtasks:
                    if not isinstance(st, dict):
                        continue
                    st_key = str(st.get("key", ""))
                    st_summary = str(st.get("summary", ""))
                    st_status = str(st.get("status", ""))
                    st_resolved = st_status.lower() in {"done", "resolved", "closed", "cancelled", "canceled"}
                    if not st_key:
                        continue

                    if st_key in by_jira_key:
                        # Update existing subtask todo
                        st_todo = by_jira_key[st_key]
                        st_todo.title = st_summary
                        if st_resolved and st_todo.status not in TERMINAL_STATUSES:
                            st_todo.status = TodoStatus.DONE
                        st_todo.updated = today
                        counts["todos_updated"] += 1
                    else:
                        # Create new child todo
                        parent_todo = by_jira_key.get(issue_key)
                        st_todo = Todo(
                            id=next_todo_id(meta, parent=parent_todo),
                            title=st_summary,
                            parent=parent_todo.id if parent_todo else None,
                            jira_issue_key=st_key,
                            status=TodoStatus.DONE if st_resolved else "pending",
                            created=today,
                            updated=today,
                        )
                        if parent_todo:
                            parent_todo.children.append(st_todo.id)
                            parent_todo.updated = today
                        todos.append(st_todo)
                        todo_map[st_todo.id] = st_todo
                        by_jira_key[st_key] = st_todo
                        counts["todos_created"] += 1

        storage.save_meta(cfg, meta)
        storage.save_todos(cfg, project_name, todos)

    return counts


# ── MCP tool registration ────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register Jira sync tools."""

    @app.tool(
        description=(
            "Map Jira issues to local projects and todos. Takes a JSON string "
            "of Jira issues (from jira_get_user_issues output). Groups issues "
            "by epic or project key, matches against existing local projects, "
            "and produces a mapping plan. Returns JSON with groups, suggested "
            "projects, and issue details including priority mapping."
        )
    )
    def proj_jira_map(
        jira_issues_json: str,
        project_name: str | None = None,
        summary_only: bool = False,
    ) -> str:
        try:
            cfg = require_project(project_name)
            if isinstance(cfg, str):
                # No active project — still allow mapping without one
                from server.tools.config import require_config
                cfg_obj = require_config()
                plan = compute_mapping(
                    json.loads(jira_issues_json), cfg_obj, project_name,
                )
                plan_dict = plan.to_dict()
                if summary_only:
                    return json.dumps({"summary": plan_dict["summary"]}, indent=2)
                return json.dumps(plan_dict, indent=2)
            cfg_obj, name = cfg
            plan = compute_mapping(
                json.loads(jira_issues_json), cfg_obj, name if project_name else None,
            )
            plan_dict = plan.to_dict()
            if summary_only:
                return json.dumps({"summary": plan_dict["summary"]}, indent=2)
            return json.dumps(plan_dict, indent=2)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    @app.tool(
        description=(
            "Apply confirmed Jira mapping to local projects and todos. Takes "
            "a JSON mapping (from proj_jira_map output, after user edits). "
            "Creates projects where needed, creates or updates todos with "
            "jira_issue_key set for idempotent re-runs. Optionally accepts "
            "comments_by_key_json mapping issue keys to comment lists. "
            "Returns counts of projects created, todos created, and todos updated."
        )
    )
    def proj_jira_apply(
        mapping_json: str,
        project_name: str | None = None,
        comments_by_key_json: str = "{}",
    ) -> str:
        try:
            raw: dict[str, Any] = json.loads(mapping_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

        try:
            cbk: dict[str, list[dict[str, Any]]] = json.loads(comments_by_key_json)
        except json.JSONDecodeError:
            cbk = {}

        try:
            cfg = require_project(project_name)
            if isinstance(cfg, str):
                from server.tools.config import require_config
                cfg_obj = require_config()
            else:
                cfg_obj, _ = cfg
        except Exception as e:
            return f"Config error: {e}"

        data = JiraApplyInput(groups=raw.get("groups", []))
        counts = apply_mapping(data, cfg_obj, comments_by_key=cbk)
        return json.dumps({"status": "ok", "counts": counts})
