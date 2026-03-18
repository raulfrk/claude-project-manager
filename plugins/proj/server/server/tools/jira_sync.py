"""MCP tools for Jira sync — map and apply."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import date
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
    """A group of Jira issues organized by epic or project key."""

    source: str  # "epic" or "project"
    jira_key: str  # Epic key or project key
    name: str  # Epic name or "KEY (no epic)"
    suggested_project: str  # Slugified project name
    project_exists: bool = False
    matched_project: str | None = None  # Name of matched local project
    issues: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "source": self.source,
            "jira_key": self.jira_key,
            "name": self.name,
            "suggested_project": self.suggested_project,
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
        }


@dataclass
class JiraApplyInput:
    """Input for applying Jira mapping to local projects."""

    groups: list[dict[str, Any]] = field(default_factory=list)


# ── Core logic (standalone functions) ─────────────────────────────────────────


def compute_mapping(
    jira_issues: list[dict[str, Any]],
    cfg: Any,
    project_name: str | None = None,
) -> JiraMappingPlan:
    """Group Jira issues by epic/project and map to local projects."""
    index = storage.load_index(cfg)
    existing_names = [
        name for name, entry in index.projects.items()
        if not entry.archived
    ]

    # Group issues by epic or project key
    epic_groups: dict[str, JiraGroup] = {}  # epic_key -> group
    project_groups: dict[str, JiraGroup] = {}  # project_key -> group

    for issue in jira_issues:
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
        subtasks = []
        if isinstance(subtasks_raw, list):
            for st in subtasks_raw:
                if isinstance(st, dict):
                    subtasks.append({
                        "key": str(st.get("key", "")),
                        "summary": str(st.get("summary", "") or str(st.get("fields", {}).get("summary", ""))),
                        "status": _parse_jira_status(st.get("fields", st) if isinstance(st.get("fields"), dict) else st),
                    })

        issue_entry: dict[str, object] = {
            "key": issue_key,
            "summary": summary,
            "priority": priority,
            "status": status,
            "labels": labels,
            "description": description,
        }
        if duedate:
            issue_entry["duedate"] = duedate
        if assignee:
            issue_entry["assignee"] = assignee
        if subtasks:
            issue_entry["subtasks"] = subtasks

        # Determine epic grouping
        parent = issue.get("parent")
        epic_key = None
        epic_name = None
        if isinstance(parent, dict):
            parent_type_raw = parent.get("fields", {})
            if isinstance(parent_type_raw, dict):
                issuetype = parent_type_raw.get("issuetype", {})
                if isinstance(issuetype, dict) and str(issuetype.get("name", "")).lower() == "epic":
                    epic_key = str(parent.get("key", ""))
                    epic_name = str(parent_type_raw.get("summary", epic_key))

        if epic_key and epic_name:
            if epic_key not in epic_groups:
                slug = _slugify(epic_name)
                matched = _fuzzy_match_project(epic_name, existing_names)
                if project_name:
                    matched = project_name
                epic_groups[epic_key] = JiraGroup(
                    source="epic",
                    jira_key=epic_key,
                    name=epic_name,
                    suggested_project=matched or slug,
                    project_exists=matched is not None,
                    matched_project=matched,
                )
            epic_groups[epic_key].issues.append(issue_entry)
        else:
            # Group by Jira project key
            proj_key = issue_key.rsplit("-", 1)[0] if "-" in issue_key else issue_key
            if proj_key not in project_groups:
                slug = _slugify(proj_key)
                matched = _fuzzy_match_project(proj_key, existing_names)
                if project_name:
                    matched = project_name
                project_groups[proj_key] = JiraGroup(
                    source="project",
                    jira_key=proj_key,
                    name=f"{proj_key} (no epic)",
                    suggested_project=matched or slug,
                    project_exists=matched is not None,
                    matched_project=matched,
                )
            project_groups[proj_key].issues.append(issue_entry)

    plan = JiraMappingPlan()
    plan.groups = list(epic_groups.values()) + list(project_groups.values())
    plan.total_issues = len(jira_issues)
    return plan


def apply_mapping(
    data: JiraApplyInput,
    cfg: Any,
) -> dict[str, int]:
    """Apply confirmed Jira mapping to local projects. Returns counts dict."""
    today = _today()
    counts = {
        "projects_created": 0,
        "todos_created": 0,
        "todos_updated": 0,
    }

    for group in data.groups:
        project_name = str(group.get("suggested_project", ""))
        if not project_name:
            continue

        create_project = group.get("create_project", False)
        project_exists = group.get("project_exists", False)

        # Create project if needed
        if create_project and not project_exists:
            proj_dir = storage.tracking_dir(cfg, project_name)
            proj_dir.mkdir(parents=True, exist_ok=True)
            from server.lib.models import ProjectDates, ProjectEntry, ProjectMeta

            meta = ProjectMeta(
                name=project_name,
                description=str(group.get("name", "")),
                dates=ProjectDates(created=today, last_updated=today),
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

        # Process issues
        issues = group.get("issues", [])
        if not isinstance(issues, list):
            continue

        try:
            meta = storage.load_meta(cfg, project_name)
        except FileNotFoundError:
            continue

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

            summary = str(issue.get("summary", ""))
            priority = str(issue.get("priority", "medium"))
            status = str(issue.get("status", ""))
            labels = issue.get("labels", [])
            labels = [str(x) for x in labels] if isinstance(labels, list) else []
            description = str(issue.get("description", "") or "")
            duedate = str(issue.get("duedate", "")) if issue.get("duedate") else None
            resolved = status.lower() in {"done", "resolved", "closed", "cancelled", "canceled"}

            if issue_key in by_jira_key:
                # Update existing todo
                todo = by_jira_key[issue_key]
                todo.title = summary
                todo.priority = priority
                todo.tags = labels
                if description and description != todo.notes:
                    todo.notes = description
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
                    notes=description,
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
                return json.dumps(plan.to_dict(), indent=2)
            cfg_obj, name = cfg
            plan = compute_mapping(
                json.loads(jira_issues_json), cfg_obj, name if project_name else None,
            )
            return json.dumps(plan.to_dict(), indent=2)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    @app.tool(
        description=(
            "Apply confirmed Jira mapping to local projects and todos. Takes "
            "a JSON mapping (from proj_jira_map output, after user edits). "
            "Creates projects where needed, creates or updates todos with "
            "jira_issue_key set for idempotent re-runs. Returns counts of "
            "projects created, todos created, and todos updated."
        )
    )
    def proj_jira_apply(
        mapping_json: str,
        project_name: str | None = None,
    ) -> str:
        try:
            raw: dict[str, Any] = json.loads(mapping_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

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
        counts = apply_mapping(data, cfg_obj)
        return json.dumps({"status": "ok", "counts": counts})
