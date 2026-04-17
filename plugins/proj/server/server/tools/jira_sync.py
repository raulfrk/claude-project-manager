"""MCP tools for Jira sync — map and apply."""

from __future__ import annotations

import base64
import difflib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, cast

from server.lib import storage
from server.lib.enums import TERMINAL_STATUSES, TodoStatus
from server.lib.ids import next_todo_id
from server.lib.models import JsonDict, ProjConfig, ProjectMeta, Todo
from server.tools.config import require_project

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_log = logging.getLogger(__name__)

# ── Priority mapping ─────────────────────────────────────────────────────────

_JIRA_TO_LOCAL: dict[str, str] = {
    "critical": "high",
    "highest": "high",
    "high": "medium",
    "medium": "medium",
    "low": "low",
    "lowest": "low",
}


_UTC = UTC


def _now() -> str:
    """Return current UTC datetime as ISO 8601 string for time precision."""
    return datetime.now(tz=_UTC).replace(tzinfo=None).isoformat()


def _today() -> str:
    return str(date.today())


_JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def _validate_jira_key(key: str) -> bool:
    """Return True if *key* matches the Jira issue key format (e.g. PROJ-123)."""
    return bool(_JIRA_KEY_RE.match(key))


_MAX_SLUG_LENGTH = 80


def _slugify(name: str) -> str:
    """Convert a name to a slug suitable for project names."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")[:_MAX_SLUG_LENGTH].rstrip("-")
    return slug or "unnamed"


def _parse_jira_priority(issue: JsonDict) -> str:
    """Map Jira priority to local priority string."""
    priority_raw = issue.get("priority")
    if isinstance(priority_raw, dict):
        name = str(priority_raw.get("name", "")).lower()
    elif isinstance(priority_raw, str):
        name = priority_raw.lower()
    else:
        return "medium"
    return _JIRA_TO_LOCAL.get(name, "medium")


def _parse_jira_status(issue: JsonDict) -> str:
    """Extract status name from Jira issue."""
    status_raw = issue.get("status")
    if isinstance(status_raw, dict):
        return str(status_raw.get("name", ""))
    if isinstance(status_raw, str):
        return status_raw
    return ""


def _is_resolved(issue: JsonDict) -> bool:
    """Check if a Jira issue is in a resolved/done state."""
    status = _parse_jira_status(issue).lower()
    return status in {"done", "resolved", "closed", "cancelled", "canceled"}


def _parse_jira_labels(issue: JsonDict) -> list[str]:
    """Extract labels list from Jira issue."""
    labels = issue.get("labels")
    return [str(x) for x in labels] if isinstance(labels, list) else []


def _parse_jira_duedate(issue: JsonDict) -> str | None:
    """Extract due date from Jira issue."""
    raw = issue.get("duedate")
    if isinstance(raw, str) and raw:
        return raw[:10]  # YYYY-MM-DD
    return None


STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        "of",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "to",
        "from",
        "up",
        "down",
        "in",
        "out",
        "on",
        "off",
        "over",
        "under",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "as",
        "until",
        "while",
        "into",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
    }
)


def _extract_keywords(text: str) -> set[str]:
    """Extract significant keywords from text.

    Splits on whitespace, lowercases, removes stopwords and words < 3 chars.
    """
    words = re.split(r"\s+", text.strip().lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


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
    lower_names = [p.lower() for p in project_names]
    matches = difflib.get_close_matches(name.lower(), lower_names, n=1, cutoff=threshold)
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
    matched_strategy: str = ""  # Strategy that produced the match
    issues: list[JsonDict] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        d: JsonDict = {
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
        if self.matched_strategy:
            d["matched_strategy"] = self.matched_strategy
        return d


@dataclass
class JiraMappingPlan:
    """Result of mapping Jira issues to local projects."""

    groups: list[JiraGroup] = field(default_factory=list)
    total_issues: int = 0

    def to_dict(self) -> JsonDict:
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
                    for g in self.groups
                    if g.needs_user_decision
                ],
            },
        }


@dataclass
class JiraApplyInput:
    """Input for applying Jira mapping to local projects."""

    groups: list[JsonDict] = field(default_factory=list)


@dataclass
class JiraApplyResult:
    """Result of applying Jira mapping — aggregate counts plus per-issue status."""

    counts: dict[str, int] = field(
        default_factory=lambda: {
            "projects_created": 0,
            "todos_created": 0,
            "todos_updated": 0,
            "skipped_unmapped": 0,
        }
    )
    per_issue: dict[str, str] = field(default_factory=dict)


# ── Notes formatting ──────────────────────────────────────────────────────────


def _format_jira_notes(issue_key: str, description: str) -> str:
    """Build the Jira section of a todo's notes from a description."""
    lines = [f"## Jira: {issue_key}", "### Description", description.strip()]
    return "\n".join(lines)


def _append_jira_comments(
    todo: Todo,
    comments: list[JsonDict],
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
        if todo.notes.strip():
            todo.notes = todo.notes.rstrip() + "\n" + comments_header
        else:
            todo.notes = comments_header
    todo.notes = todo.notes.rstrip() + "\n" + "\n".join(new_parts)
    todo.jira_synced_comment_ids.extend(new_ids)


def _sync_root_issue_to_notes(
    cfg: ProjConfig,
    project_name: str,
    meta: ProjectMeta,
    issue: JsonDict,
    comments: list[JsonDict],
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


def _build_issue_entry(issue: JsonDict) -> JsonDict:
    """Extract a normalised issue entry dict from a raw Jira issue."""
    # Read from nested "fields" dict when present (real Jira API), fall back
    # to top-level keys for pre-normalised / test data.
    fields_raw = issue.get("fields", issue)
    fields: JsonDict = fields_raw if isinstance(fields_raw, dict) else {}
    issue_key = str(issue.get("key", ""))
    summary = str(fields.get("summary", ""))
    priority = _parse_jira_priority(fields)
    status = _parse_jira_status(fields)
    labels = _parse_jira_labels(fields)
    duedate = _parse_jira_duedate(fields)
    description = str(fields.get("description", "") or "")
    assignee_raw = fields.get("assignee")
    assignee = ""
    if isinstance(assignee_raw, dict):
        assignee = str(assignee_raw.get("displayName", "") or assignee_raw.get("name", ""))
    elif isinstance(assignee_raw, str):
        assignee = assignee_raw

    subtasks_raw = fields.get("subtasks", [])
    subtasks: list[JsonDict] = []
    if isinstance(subtasks_raw, list):
        for st in subtasks_raw:
            if isinstance(st, dict):
                st_fields = st.get("fields")
                st_fields_dict = st_fields if isinstance(st_fields, dict) else {}
                subtasks.append(
                    {
                        "key": str(st.get("key", "")),
                        "summary": str(st.get("summary", "") or st_fields_dict.get("summary", "")),
                        "status": _parse_jira_status(st_fields_dict if st_fields_dict else st),
                    }
                )

    entry: JsonDict = {
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


def _detect_epic_key(issue: JsonDict) -> tuple[str | None, str | None]:
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
                epic_key_str = str(parent.get("key", ""))
                epic_summary = str(parent_fields.get("summary", epic_key_str))
                return epic_key_str, epic_summary

    return None, None


def _is_epic_issue(issue: JsonDict) -> bool:
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


def _match_by_jira_key(jira_key: str, cfg: ProjConfig, existing_names: list[str]) -> str | None:
    """Look up an existing project by its jira_issue_key metadata field."""
    for name in existing_names:
        try:
            meta = storage.load_meta(cfg, name)
            if meta.jira_issue_key == jira_key:
                return name
        except FileNotFoundError:
            continue
    return None


def _match_standalone(
    issue: JsonDict,
    existing_names: list[str],
    cfg: ProjConfig,
) -> tuple[str | None, str, list[str]]:
    """Try a chain of strategies to match a standalone Jira issue to a project.

    Returns (matched_project, strategy_name, suggestions).
    Strategies tried in order: jira_issue_key, fuzzy_name, tag_match,
    keyword_match, recent_suggestion.
    """
    issue_key = str(issue.get("key", ""))
    summary = str(issue.get("summary", ""))
    description = str(issue.get("description", "") or "")
    labels = _parse_jira_labels(issue)

    # 1. jira_issue_key lookup
    matched = _match_by_jira_key(issue_key, cfg, existing_names)
    if matched is not None:
        return matched, "jira_issue_key", []

    # 2. fuzzy name match
    matched = _fuzzy_match_project(summary, existing_names)
    if matched is not None:
        return matched, "fuzzy_name", []

    # 3. tag-based match (Jira labels vs project tags, case-insensitive)
    if labels:
        label_set = {lbl.lower() for lbl in labels}
        tag_matches: list[str] = []
        for name in existing_names:
            try:
                meta = storage.load_meta(cfg, name)
                if meta.tags and label_set & {t.lower() for t in meta.tags}:
                    tag_matches.append(name)
            except FileNotFoundError:
                continue
        if len(tag_matches) == 1:
            return tag_matches[0], "tag_match", []
        if len(tag_matches) > 1:
            return None, "tag_match_ambiguous", tag_matches

    # 4. keyword match (summary + description keywords vs project name/description)
    keywords = _extract_keywords(summary + " " + description)
    if keywords:
        kw_matches: list[str] = []
        for name in existing_names:
            name_lower = name.lower()
            if keywords & _extract_keywords(name_lower):
                kw_matches.append(name)
                continue
            try:
                meta = storage.load_meta(cfg, name)
                if meta.description and keywords & _extract_keywords(meta.description):
                    kw_matches.append(name)
            except FileNotFoundError:
                continue
        if len(kw_matches) == 1:
            return kw_matches[0], "keyword_match", []
        if len(kw_matches) > 1:
            return None, "keyword_match_ambiguous", kw_matches

    # 5. recently-active suggestion (sorted by last_updated desc)
    projects_with_dates: list[tuple[str, str]] = []
    for name in existing_names:
        try:
            meta = storage.load_meta(cfg, name)
            projects_with_dates.append((name, meta.dates.last_updated or ""))
        except FileNotFoundError:
            continue
    if projects_with_dates:
        projects_with_dates.sort(key=lambda x: x[1], reverse=True)
        top = projects_with_dates[0][0]
        return top, "recent_suggestion", [top]

    # 6. No match at all
    return None, "none", []


def _link_standalone_key(group: JiraGroup, cfg: ProjConfig) -> None:
    """Link jira_issue_key on todos for matched standalone issues.

    For each issue in *group*, loads the matched project's todos, checks if a
    todo with the issue's jira_issue_key already exists, and creates a minimal
    todo if not.  Saves todos and meta to disk.

    Logs a warning on storage failure but does not raise — the mapping plan is
    still returned even if key linking fails.
    """
    project_name = group.matched_project
    if not project_name:
        return

    try:
        meta = storage.load_meta(cfg, project_name)
        todos = storage.load_todos(cfg, project_name)
    except FileNotFoundError:
        _log.warning("Cannot link jira keys: project %s not found", project_name)
        return

    by_jira_key: dict[str, Todo] = {t.jira_issue_key: t for t in todos if t.jira_issue_key}
    changed = False

    for issue in group.issues:
        issue_key = str(issue.get("key", ""))
        if not issue_key:
            continue
        if not _validate_jira_key(issue_key):
            _log.warning("Skipping issue with invalid key format: %s", issue_key)
            continue
        if issue_key in by_jira_key:
            continue  # already linked — idempotent
        summary = str(issue.get("summary", ""))
        todo = Todo(
            id=next_todo_id(meta),
            title=summary,
            jira_issue_key=issue_key,
            status="pending",
            created=_today(),
            updated=_today(),
        )
        todos.append(todo)
        by_jira_key[issue_key] = todo
        changed = True

    if changed:
        try:
            storage.save_todos(cfg, project_name, todos)
            storage.save_meta(cfg, meta)
        except Exception:
            _log.warning(
                "Failed to save jira key linking for project %s",
                project_name,
                exc_info=True,
            )


def compute_mapping(
    jira_issues: list[JsonDict],
    cfg: ProjConfig,
    project_name: str | None = None,
    link_keys: bool = True,
) -> JiraMappingPlan:
    """Group Jira issues by epic (epic-first) and map to local projects.

    Logic:
    1. Separate epics from non-epics
    2. For each epic: create JiraGroup with is_epic=True, child issues as sub-items
    3. For non-epic with epic parent: add to that epic's group
    4. For issues with no epic: create standalone group with needs_user_decision=True
    5. Match against existing projects by jira_issue_key first, then fuzzy name
    6. No catchall/default project — unmapped issues stay as "unmapped"

    Side effect: when *link_keys* is True (default), standalone issues that are
    auto-matched to a project (i.e. ``needs_user_decision is False``) will have
    a todo with their ``jira_issue_key`` created in the matched project's todo
    list if one does not already exist.  This ensures the mapping persists even
    if ``apply_mapping()`` is never called.  Pass ``link_keys=False`` for
    dry-run mode with no storage writes.
    """
    index = storage.load_index(cfg)
    existing_names = [name for name, entry in index.projects.items() if not entry.archived]

    # Phase 1: separate epics and collect epic metadata
    epic_groups: dict[str, JiraGroup] = {}  # epic_key -> group
    non_epic_issues: list[JsonDict] = []

    epic_key: str | None
    epic_name: str | None
    for issue in jira_issues:
        if _is_epic_issue(issue):
            epic_key = str(issue.get("key", ""))
            epic_name = str(issue.get("summary", ""))
            if not epic_key:
                continue
            if epic_key not in epic_groups:
                # Match: jira_issue_key on project first, then fuzzy name
                matched: str | None
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
    standalone_issues: list[tuple[JsonDict, JsonDict]] = []

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

    # Phase 3: create standalone groups using strategy chain
    standalone_groups: list[JiraGroup] = []
    for issue, issue_entry in standalone_issues:
        issue_key = str(issue.get("key", ""))
        summary = str(issue.get("summary", ""))
        if project_name:
            matched = project_name
            strategy = "project_name_override"
            needs_decision = False
        else:
            matched, strategy, _suggestions = _match_standalone(issue, existing_names, cfg)
            needs_decision = strategy in {
                "recent_suggestion",
                "tag_match_ambiguous",
                "keyword_match_ambiguous",
                "none",
            }
        slug = _slugify(summary)
        standalone_groups.append(
            JiraGroup(
                source="standalone",
                jira_key=issue_key,
                name=summary,
                suggested_project=matched or "",
                is_epic=False,
                needs_user_decision=needs_decision,
                project_exists=matched is not None,
                matched_project=matched,
                matched_strategy=strategy,
                issues=[issue_entry],
            )
        )

    # Phase 3b: Early jira_issue_key linking (side effect: writes to storage)
    if link_keys:
        for group in standalone_groups:
            if group.needs_user_decision or not group.matched_project:
                continue
            _link_standalone_key(group, cfg)

    plan = JiraMappingPlan()
    plan.groups = list(epic_groups.values()) + standalone_groups
    plan.total_issues = len(jira_issues)
    return plan


def apply_mapping(
    data: JiraApplyInput,
    cfg: ProjConfig,
    comments_by_key: dict[str, list[JsonDict]] | None = None,
    todo_key_index: dict[str, tuple[str, str]] | None = None,
) -> JiraApplyResult:
    """Apply confirmed Jira mapping to local projects.

    Returns a :class:`JiraApplyResult` with aggregate counts (backward
    compatible) and per-issue status for transparency.

    Each issue is processed independently — a failure on one issue does not
    prevent processing of subsequent issues.  Progress is saved after each
    successful issue so partial results survive failures.

    When creating a project from an epic group, sets jira_issue_key on the
    ProjectMeta so that re-runs can instantly match the epic to the project.
    Groups with no suggested_project (unmapped) are skipped.

    *comments_by_key* maps issue keys to lists of Jira comment dicts.
    Each comment dict should have ``id``, ``author``, ``created``, ``body``.
    """
    if comments_by_key is None:
        comments_by_key = {}
    today = _now()
    result = JiraApplyResult()

    for group in data.groups:
        project_name = str(group.get("suggested_project", ""))
        if not project_name:
            issues = group.get("issues", [])
            result.counts["skipped_unmapped"] += len(issues) if isinstance(issues, list) else 0
            continue

        create_project = group.get("create_project", False)
        project_exists = group.get("project_exists", False)
        is_epic = group.get("is_epic", False)
        jira_key = str(group.get("jira_key", ""))

        # Create project if needed — failure marks all issues in group as failed
        if create_project and not project_exists:
            try:
                proj_dir = storage.tracking_dir(cfg, project_name)

                # Dedup guard: if meta already exists (partial previous run
                # created dir+meta but failed before updating index), repair
                # the index entry instead of recreating the project.
                meta_path = proj_dir / "meta.yaml"
                if meta_path.exists():
                    _log.warning(
                        "Skipping duplicate project creation: meta already exists for '%s'",
                        project_name,
                    )
                    from server.lib.models import ProjectEntry

                    index = storage.load_index(cfg)
                    if project_name not in index.projects:
                        index.projects[project_name] = ProjectEntry(
                            name=project_name,
                            tracking_dir=str(proj_dir),
                            created=today,
                        )
                        storage.save_index(cfg, index)
                        result.counts["projects_created"] += 1
                else:
                    proj_dir.mkdir(parents=True, exist_ok=True)
                    from server.lib.models import ProjectDates, ProjectEntry, ProjectMeta

                    group_labels = group.get("labels", [])
                    group_tags = (
                        [str(lbl) for lbl in group_labels] if isinstance(group_labels, list) else []
                    )
                    meta = ProjectMeta(
                        name=project_name,
                        description=str(group.get("name", "")),
                        dates=ProjectDates(created=today, last_updated=today),
                        jira_issue_key=jira_key,
                        tags=group_tags,
                    )
                    storage.save_meta(cfg, meta)
                    (proj_dir / "todos.yaml").write_text("todos: []\n")
                    (proj_dir / "archive.yaml").write_text("todos: []\n")

                    index = storage.load_index(cfg)
                    index.projects[project_name] = ProjectEntry(
                        name=project_name,
                        tracking_dir=str(proj_dir),
                        created=today,
                    )
                    storage.save_index(cfg, index)
                    result.counts["projects_created"] += 1

                    # Append epic description/comments to project NOTES.md
                    if is_epic:
                        epic_desc = str(group.get("description", "") or "")
                        note_parts: list[str] = []
                        if epic_desc:
                            note_parts.append(
                                f"## Jira: {jira_key}\n### Description\n{epic_desc.strip()}"
                            )
                        epic_comments = comments_by_key.get(jira_key, [])
                        if epic_comments:
                            comment_lines: list[str] = []
                            for ec in epic_comments:
                                ec_author_raw = ec.get("author")
                                if isinstance(ec_author_raw, dict):
                                    ec_author = str(
                                        ec_author_raw.get("displayName", "")
                                        or ec_author_raw.get("name", "")
                                    )
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
                        if epic_comments:
                            meta.jira_synced_comment_ids = [
                                str(ec.get("id", "")) for ec in epic_comments if ec.get("id")
                            ]
                            storage.save_meta(cfg, meta)
            except Exception as exc:
                # Project creation failed — mark all issues in group as failed
                _log.error(
                    "Project creation failed for jira_key=%s: %s",
                    group.get("jira_key", "<unknown>"),
                    exc,
                    exc_info=True,
                )
                group_issues = group.get("issues", [])
                if isinstance(group_issues, list):
                    for gi in group_issues:
                        if isinstance(gi, dict):
                            gi_key = str(gi.get("key", ""))
                            if gi_key:
                                result.per_issue[gi_key] = f"failed: project creation failed: {exc}"
                continue

        # Process issues
        issues = group.get("issues", [])
        if not isinstance(issues, list):
            continue

        try:
            meta = storage.load_meta(cfg, project_name)
        except FileNotFoundError:
            for gi in issues:
                if isinstance(gi, dict):
                    gi_key = str(gi.get("key", ""))
                    if gi_key:
                        result.per_issue[gi_key] = "failed: project not found"
            continue

        # On re-run: ensure jira_issue_key is set on the project
        if jira_key and not meta.jira_issue_key:
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
            if not _validate_jira_key(issue_key):
                _log.warning("Skipping issue with invalid key format: %s", issue_key)
                result.per_issue[issue_key] = "skipped:invalid_key_format"
                continue

            try:
                if is_epic and issue_key == meta.jira_issue_key:
                    # Root epic issue -> NOTES.md, not a todo
                    _sync_root_issue_to_notes(
                        cfg, project_name, meta, issue, comments_by_key.get(issue_key, [])
                    )
                    # If the epic itself is resolved, mark project as done
                    epic_status = str(issue.get("status", "")).lower()
                    if epic_status in _DONE_STATUSES and meta.status != "complete":
                        meta.status = "complete"
                    result.per_issue[issue_key] = "skipped"
                    storage.save_meta(cfg, meta)
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
                    result.counts["todos_updated"] += 1
                    issue_status = "updated"
                elif todo_key_index and issue_key in todo_key_index:
                    # Todo with this jira_issue_key exists in another project — skip
                    existing_proj, existing_id = todo_key_index[issue_key]
                    _log.info(
                        "Dedup: %s already linked to todo %s in project %s, skipping",
                        issue_key,
                        existing_id,
                        existing_proj,
                    )
                    result.per_issue[issue_key] = (
                        f"skipped: already exists as {existing_id} in {existing_proj}"
                    )
                    result.counts.setdefault("skipped_dedup", 0)
                    result.counts["skipped_dedup"] += 1
                    continue
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
                    result.counts["todos_created"] += 1
                    issue_status = "created"

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
                        st_resolved = st_status.lower() in _DONE_STATUSES
                        if not st_key:
                            continue

                        if st_key in by_jira_key:
                            st_todo = by_jira_key[st_key]
                            st_todo.title = st_summary
                            if st_resolved and st_todo.status not in TERMINAL_STATUSES:
                                st_todo.status = TodoStatus.DONE
                            st_todo.updated = today
                            result.counts["todos_updated"] += 1
                        else:
                            parent_todo = by_jira_key.get(issue_key)
                            # Flat model: sub-task becomes a sibling todo tagged
                            # group:<parent_todo.id> — no parent/children kwargs.
                            _st_labels = st.get("labels")
                            subtask_tags: list[str] = (
                                [str(x) for x in _st_labels] if isinstance(_st_labels, list) else []
                            )
                            if parent_todo:
                                subtask_tags.append(f"group:{parent_todo.id}")
                            st_todo = Todo(
                                id=next_todo_id(meta),
                                title=st_summary,
                                tags=subtask_tags,
                                jira_issue_key=st_key,
                                status=TodoStatus.DONE if st_resolved else "pending",
                                created=today,
                                updated=today,
                            )
                            todos.append(st_todo)
                            todo_map[st_todo.id] = st_todo
                            by_jira_key[st_key] = st_todo
                            result.counts["todos_created"] += 1

                # Save after each successful issue
                storage.save_todos(cfg, project_name, todos)
                storage.save_meta(cfg, meta)
                result.per_issue[issue_key] = issue_status

            except Exception as exc:
                _log.error(
                    "Failed to apply jira issue %s: %s",
                    issue_key,
                    exc,
                    exc_info=True,
                )
                result.per_issue[issue_key] = f"failed: {exc}"
                continue

    return result


# ── Deterministic mapping (full-sync) ────────────────────────────────────────

_DONE_STATUSES = frozenset({"done", "resolved", "closed", "cancelled", "canceled"})

_MAX_PROJECTS_CREATED = 10


def _title_similarity(a: str, b: str) -> float:
    """Return SequenceMatcher ratio between two title strings."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _sanitize_project_name(summary: str) -> str:
    """Build a standalone project name from an issue key and summary."""
    clean = re.sub(r"[^a-zA-Z0-9 _-]", "", summary)
    return clean[:60].strip() or "unnamed"


def _match_todo_by_title(
    summary: str,
    todos: list[Todo],
    threshold: float = 0.8,
) -> Todo | None:
    """Legacy fallback: find a todo by title similarity when jira_issue_key is unset."""
    for todo in todos:
        if todo.jira_issue_key:
            continue  # already linked, skip
        if _title_similarity(summary, todo.title) >= threshold:
            return todo
    return None


def _deterministic_map(
    jira_issues: list[JsonDict],
    cfg: ProjConfig,
    name: str | None = None,
) -> tuple[JiraApplyInput, JsonDict]:
    """Build a deterministic mapping without interactive disambiguation.

    Returns ``(apply_input, diagnostics)`` where *diagnostics* carries
    warnings and summary counts for the caller.

    Routing rules:
    - Case A — Epic issues route to a **project** (one project per epic).
    - Case B — Epic children (epic in our issues list) route as **todos**
      inside the epic's project.
    - Case C — No epic or foreign/ghost epic → standalone project per issue
      (tagged ``jira-standalone``).
    - Dedup: ``todo_key_index`` checked before creating any todo.
    - Legacy fallback: match by title similarity when ``jira_issue_key``
      is not set on existing todos.
    - Status: Jira "Done"/"Closed"/"Resolved" → complete; reopened + local
      done → set pending.
    """
    index = storage.load_index(cfg)
    existing_names = [n for n, e in index.projects.items() if not e.archived]

    # Pre-load all project metas for jira_issue_key lookup
    meta_by_jira_key: dict[str, str] = {}  # jira_key -> project_name
    all_metas: dict[str, ProjectMeta] = {}
    for pn in existing_names:
        try:
            meta = storage.load_meta(cfg, pn)
            all_metas[pn] = meta
            if meta.jira_issue_key:
                meta_by_jira_key[meta.jira_issue_key] = pn
        except FileNotFoundError:
            continue

    # Step 1: Build todo_key_index: jira_key -> (project_name, todo_id)
    todo_key_index: dict[str, tuple[str, str]] = {}
    for pn in existing_names:
        try:
            todos = storage.load_todos(cfg, pn)
            for todo in todos:
                if todo.jira_issue_key:
                    todo_key_index[todo.jira_issue_key] = (pn, todo.id)
        except (FileNotFoundError, Exception):
            _log.debug("Failed to load todos for project %s", pn, exc_info=True)
            continue

    # Step 2: Identify which issues are epics in our fetched set
    own_epic_keys: set[str] = set()
    for issue in jira_issues:
        if _is_epic_issue(issue):
            ek = str(issue.get("key", ""))
            if ek:
                own_epic_keys.add(ek)

    # Phase 1: classify each issue
    epic_issues: dict[str, JsonDict] = {}  # epic_key -> epic issue
    children_by_epic: dict[str, list[JsonDict]] = {}
    standalone: list[JsonDict] = []

    for issue in jira_issues:
        if _is_epic_issue(issue):
            # Case A: Epic -> project
            ek = str(issue.get("key", ""))
            if ek:
                epic_issues[ek] = issue
                children_by_epic.setdefault(ek, [])
        else:
            epic_key, _epic_name = _detect_epic_key(issue)
            if epic_key and epic_key in own_epic_keys:
                # Case B: Epic child whose epic is in our issues list
                children_by_epic.setdefault(epic_key, []).append(issue)
            else:
                # Case C/D: No epic, foreign epic, or ghost epic -> standalone
                standalone.append(issue)

    groups: list[JsonDict] = []
    warnings: list[str] = []
    projects_to_create = 0

    # Phase 2: map epics to projects (Case A)
    for epic_key, epic_issue in epic_issues.items():
        epic_name = str(epic_issue.get("summary", ""))
        slug = _slugify(epic_name)
        children = children_by_epic.get(epic_key, [])
        issue_entries = [_build_issue_entry(c) for c in children]

        matched_project: str | None = None
        create_project = False
        project_exists = False

        # Match by jira_issue_key
        if epic_key in meta_by_jira_key:
            matched_project = meta_by_jira_key[epic_key]
            project_exists = True
        elif name:
            # Caller-specified project override
            matched_project = name
            project_exists = name in existing_names
        else:
            # Fuzzy match
            matched_project = _fuzzy_match_project(epic_name, existing_names)
            if matched_project:
                project_exists = True
            else:
                # Auto-create
                if projects_to_create < _MAX_PROJECTS_CREATED:
                    matched_project = slug
                    create_project = True
                    projects_to_create += 1
                    # Warn if >80% similarity with existing project
                    for en in existing_names:
                        if _title_similarity(epic_name, en) > 0.8:
                            warnings.append(
                                f"New project '{slug}' from epic {epic_key} is >80% similar"
                                f" to existing '{en}' — potential duplicate"
                            )
                            break
                else:
                    warnings.append(
                        f"Auto-create cap ({_MAX_PROJECTS_CREATED}) reached;"
                        f" epic {epic_key} ({epic_name}) skipped"
                    )
                    continue

        groups.append(
            {
                "source": "epic",
                "jira_key": epic_key,
                "name": epic_name,
                "suggested_project": matched_project or "",
                "is_epic": True,
                "project_exists": project_exists,
                "create_project": create_project,
                "description": str(epic_issue.get("description", "") or ""),
                "issues": issue_entries,
                "labels": ["jira-epic"],
            }
        )

    # Phase 3: map standalone issues (Case C/D) — each gets its own project
    standalone_projects_created = 0
    for issue in standalone:
        issue_entry = _build_issue_entry(issue)
        issue_key = str(issue.get("key", ""))
        summary = str(issue.get("summary", ""))

        if name:
            # Caller provided a project override
            groups.append(
                {
                    "source": "standalone",
                    "jira_key": issue_key,
                    "name": summary,
                    "suggested_project": name,
                    "is_epic": False,
                    "project_exists": name in existing_names,
                    "create_project": False,
                    "issues": [issue_entry],
                    "labels": ["jira-standalone"],
                }
            )
        else:
            # Check dedup: already linked via todo_key_index
            if issue_key in todo_key_index:
                found_project = todo_key_index[issue_key][0]
                groups.append(
                    {
                        "source": "standalone",
                        "jira_key": issue_key,
                        "name": summary,
                        "suggested_project": found_project,
                        "is_epic": False,
                        "project_exists": True,
                        "create_project": False,
                        "issues": [issue_entry],
                        "labels": ["jira-standalone"],
                    }
                )
            elif issue_key in meta_by_jira_key:
                # Project already exists for this issue key
                found_project = meta_by_jira_key[issue_key]
                groups.append(
                    {
                        "source": "standalone",
                        "jira_key": issue_key,
                        "name": summary,
                        "suggested_project": found_project,
                        "is_epic": False,
                        "project_exists": True,
                        "create_project": False,
                        "issues": [issue_entry],
                        "labels": ["jira-standalone"],
                    }
                )
            else:
                # Legacy fallback: search by jira_issue_key on todos (O(n) scan)
                found_project = None
                for pn in existing_names:
                    try:
                        todos = storage.load_todos(cfg, pn)
                        if any(t.jira_issue_key == issue_key for t in todos):
                            found_project = pn
                            break
                        # Case E: legacy name fallback — match by title
                        matched_todo = _match_todo_by_title(summary, todos)
                        if matched_todo:
                            found_project = pn
                            break
                    except FileNotFoundError:
                        continue

                if found_project:
                    groups.append(
                        {
                            "source": "standalone",
                            "jira_key": issue_key,
                            "name": summary,
                            "suggested_project": found_project,
                            "is_epic": False,
                            "project_exists": True,
                            "create_project": False,
                            "issues": [issue_entry],
                            "labels": ["jira-standalone"],
                        }
                    )
                else:
                    # Create a dedicated standalone project for this issue
                    proj_name = f"{issue_key}: {_sanitize_project_name(summary)}"
                    slug = _slugify(proj_name)
                    if standalone_projects_created < _MAX_PROJECTS_CREATED:
                        groups.append(
                            {
                                "source": "standalone",
                                "jira_key": issue_key,
                                "name": summary,
                                "suggested_project": slug,
                                "is_epic": False,
                                "project_exists": False,
                                "create_project": True,
                                "issues": [issue_entry],
                                "labels": ["jira-standalone"],
                            }
                        )
                        standalone_projects_created += 1
                    else:
                        warnings.append(
                            f"Standalone project cap ({_MAX_PROJECTS_CREATED}) reached;"
                            f" issue {issue_key} ({summary}) skipped"
                        )

    # Phase 4: handle status reopened -> pending
    for group in groups:
        project_name = str(group.get("suggested_project", ""))
        if not project_name or not group.get("project_exists"):
            continue
        try:
            todos = storage.load_todos(cfg, project_name)
        except FileNotFoundError:
            continue
        by_jira_key = {t.jira_issue_key: t for t in todos if t.jira_issue_key}
        changed = False
        issues_raw = group.get("issues", [])
        for ie in issues_raw if isinstance(issues_raw, list) else []:
            if not isinstance(ie, dict):
                continue
            ik = str(ie.get("key", ""))
            status_str = str(ie.get("status", "")).lower()
            if ik in by_jira_key:
                todo = by_jira_key[ik]
                is_jira_done = status_str in _DONE_STATUSES
                is_local_done = todo.status in TERMINAL_STATUSES
                # Reopened: Jira not-done but local is done
                if not is_jira_done and is_local_done:
                    todo.status = "pending"
                    todo.updated = _now()
                    changed = True
        if changed:
            storage.save_todos(cfg, project_name, todos)

    diagnostics: JsonDict = {
        "warnings": warnings,
        "epic_count": len(epic_issues),
        "standalone_count": len(standalone),
        "groups_mapped": len(groups),
        "projects_to_create": projects_to_create + standalone_projects_created,
        "todo_key_index": todo_key_index,
    }

    return JiraApplyInput(groups=groups), diagnostics


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
                    json.loads(jira_issues_json),
                    cfg_obj,
                    project_name,
                )
                plan_dict = plan.to_dict()
                if summary_only:
                    return json.dumps({"summary": plan_dict["summary"]}, indent=2)
                return json.dumps(plan_dict, indent=2)
            cfg_obj, name = cfg
            plan = compute_mapping(
                json.loads(jira_issues_json),
                cfg_obj,
                name if project_name else None,
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
            "Returns counts of projects created, todos created, todos updated, "
            "and per-issue status (created/updated/skipped/failed)."
        )
    )
    def proj_jira_apply(
        mapping_json: str,
        project_name: str | None = None,
        comments_by_key_json: str = "{}",
    ) -> str:
        try:
            raw: JsonDict = json.loads(mapping_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

        try:
            cbk: dict[str, list[JsonDict]] = json.loads(comments_by_key_json)
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

        groups_raw = raw.get("groups", [])
        data = JiraApplyInput(
            groups=[g for g in groups_raw if isinstance(g, dict)]
            if isinstance(groups_raw, list)
            else []
        )
        apply_result = apply_mapping(data, cfg_obj, comments_by_key=cbk)
        response: JsonDict = {
            "status": "ok",
            "counts": apply_result.counts,
        }
        # Include per_issue details when there are failures
        failed = {k: v for k, v in apply_result.per_issue.items() if v.startswith("failed:")}
        if failed:
            response["status"] = "partial"
            response["per_issue"] = apply_result.per_issue
        return json.dumps(response)


# -- Callable helper (used by proj_sync dispatcher) --------------------------


def _run_jira_full_sync(
    jira_issues_json: str | None = None,
    project_name: str | None = None,
    comments_json: str = "{}",
    retry_failures: str | None = None,
) -> str:
    """Full Jira sync cycle — callable without MCP registration."""
    try:
        cfg = require_project(project_name)
        if isinstance(cfg, str):
            from server.tools.config import require_config

            cfg_obj = require_config()
        else:
            cfg_obj, project_name = cfg
    except Exception as e:
        return json.dumps({"status": "error", "error": f"Config error: {e}"})

    # Parse comments
    try:
        comments_by_key: dict[str, list[JsonDict]] = json.loads(comments_json)
    except json.JSONDecodeError:
        comments_by_key = {}

    # ── Retry path ───────────────────────────────────────────────
    if retry_failures:
        try:
            token_data = json.loads(base64.b64decode(retry_failures).decode())
        except Exception:
            return json.dumps({"status": "error", "error": "Invalid retry_token"})

        ts = token_data.get("ts", 0)
        if time.time() - ts > 1800:  # 30 minutes
            return json.dumps(
                {
                    "status": "error",
                    "error": "Retry token expired (>30 min). Run a fresh sync.",
                }
            )

        retry_issues: list[JsonDict] = []
        for err_entry in token_data.get("errors", []):
            payload = err_entry.get("retry_payload", {})
            issue = payload.get("issue")
            if isinstance(issue, dict):
                retry_issues.append(issue)

        if not retry_issues:
            return json.dumps(
                {
                    "status": "success",
                    "summary": {"message": "No retryable issues found"},
                }
            )

        # Dedup guard: filter out retry issues that were already
        # successfully applied (have a matching todo with jira_issue_key)
        # in a previous partial run.
        try:
            all_projects = storage.load_index(cfg_obj)
            existing_jira_keys: set[str] = set()
            for pn, pe in all_projects.projects.items():
                if pe.archived:
                    continue
                try:
                    p_todos = storage.load_todos(cfg_obj, pn)
                    for t in p_todos:
                        if t.jira_issue_key:
                            existing_jira_keys.add(t.jira_issue_key)
                except Exception:
                    _log.debug(
                        "Failed to load todos for dedup scan of project %s",
                        pn,
                        exc_info=True,
                    )
            filtered: list[JsonDict] = []
            for ri in retry_issues:
                ri_key = str(ri.get("key", ""))
                if ri_key and ri_key in existing_jira_keys:
                    _log.warning(
                        "Skipping duplicate on retry: issue %s already has a linked todo",
                        ri_key,
                    )
                else:
                    filtered.append(ri)
            retry_issues = filtered
        except Exception:
            _log.debug("Dedup scan failed, proceeding with all retry issues", exc_info=True)

        if not retry_issues:
            return json.dumps(
                {
                    "status": "success",
                    "summary": {"message": "All retry issues already applied"},
                }
            )

        jira_issues_parsed: list[JsonDict] = retry_issues
    else:
        # ── Normal path ──────────────────────────────────────────
        if jira_issues_json is None:
            # Self-fetch via inter-plugin socket
            try:
                from server.tools.jira_full_sync import _fetch_jira_issues

                jira_issues_parsed, _ = _fetch_jira_issues()
            except Exception as e:
                return json.dumps(
                    {
                        "status": "error",
                        "error": str(e),
                        "guidance": (
                            "Jira plugin socket unreachable. Ensure the Jira plugin is running."
                        ),
                    }
                )
        elif isinstance(jira_issues_json, str):
            try:
                raw_parsed = json.loads(jira_issues_json)
                if isinstance(raw_parsed, dict) and "issues" in raw_parsed:
                    raw_parsed = raw_parsed["issues"]
                jira_issues_parsed = (
                    [x for x in raw_parsed if isinstance(x, dict)]
                    if isinstance(raw_parsed, list)
                    else []
                )
            except json.JSONDecodeError as e:
                return json.dumps({"status": "error", "error": f"Invalid JSON: {e}"})

    if not jira_issues_parsed:
        return json.dumps(
            {
                "status": "success",
                "summary": {"message": "Everything up to date"},
            }
        )

    # Deterministic mapping
    try:
        apply_input, diagnostics = _deterministic_map(
            jira_issues_parsed,
            cfg_obj,
            project_name,
        )
    except Exception as e:
        return json.dumps({"status": "error", "error": f"Mapping error: {e}"})

    if not apply_input.groups:
        return json.dumps(
            {
                "status": "success",
                "summary": {
                    "message": "No mappable issues",
                    "warnings": diagnostics.get("warnings", []),
                },
            }
        )

    # Apply with per-issue error tracking
    errors: list[JsonDict] = []
    safe_groups: list[JsonDict] = []
    todo_key_idx_raw = diagnostics.get("todo_key_index")
    todo_key_idx: dict[str, tuple[str, str]] | None = (
        cast("dict[str, tuple[str, str]]", todo_key_idx_raw)
        if isinstance(todo_key_idx_raw, dict)
        else None
    )
    counts: dict[str, int] = {
        "epics_mapped": 0,
        "standalone_created": 0,
        "todos_created": 0,
        "todos_updated": 0,
        "duplicates_skipped": 0,
        "total_issues": len(jira_issues_parsed),
    }

    for group in apply_input.groups:
        try:
            single_input = JiraApplyInput(groups=[group])
            _result = apply_mapping(
                single_input,
                cfg_obj,
                comments_by_key=comments_by_key,
                todo_key_index=todo_key_idx,
            )
            # Accumulate counts
            counts["todos_created"] += _result.counts.get("todos_created", 0)
            counts["todos_updated"] += _result.counts.get("todos_updated", 0)
            counts["duplicates_skipped"] += _result.counts.get("skipped_dedup", 0)
            if group.get("is_epic"):
                counts["epics_mapped"] += 1
            elif group.get("create_project") and _result.counts.get("projects_created", 0) > 0:
                counts["standalone_created"] += 1
            elif group.get("source") == "standalone" and not group.get("project_exists"):
                counts["standalone_created"] += _result.counts.get("projects_created", 0)
            # Check per-issue failures
            for ik, status in _result.per_issue.items():
                if status.startswith("failed:"):
                    # Find the original issue dict for retry
                    issue_dict = None
                    group_issues = group.get("issues", [])
                    for ie in group_issues if isinstance(group_issues, list) else []:
                        if isinstance(ie, dict) and str(ie.get("key", "")) == ik:
                            issue_dict = ie
                            break
                    errors.append(
                        {
                            "issue_key": ik,
                            "operation_type": "apply",
                            "error": status,
                            "retryable": True,
                            "retry_payload": {"issue": issue_dict} if issue_dict else {},
                        }
                    )
            safe_groups.append(group)
        except Exception as e:
            jk = str(group.get("jira_key", ""))
            exc_issues = group.get("issues", [])
            for ie in exc_issues if isinstance(exc_issues, list) else []:
                if isinstance(ie, dict):
                    errors.append(
                        {
                            "issue_key": str(ie.get("key", jk)),
                            "operation_type": "apply",
                            "error": str(e),
                            "retryable": True,
                            "retry_payload": {"issue": ie},
                        }
                    )

    # Build summary
    summary: JsonDict = {
        "groups_processed": len(safe_groups),
        "warnings": diagnostics.get("warnings", []),
        "epic_count": diagnostics.get("epic_count", 0),
        "standalone_count": diagnostics.get("standalone_count", 0),
        "projects_to_create": diagnostics.get("projects_to_create", 0),
        "comments_synced": sum(len(v) for v in comments_by_key.values()) if comments_by_key else 0,
    }

    # Ensure warnings are plain strings (not Warning objects)
    warnings_raw = summary.get("warnings", [])
    summary["warnings"] = [str(w) for w in warnings_raw] if isinstance(warnings_raw, list) else []

    if errors:
        # Strip retry_payload and retryable from user-facing errors
        clean_errors = [{"issue_key": e["issue_key"], "error": e["error"]} for e in errors]
        retry_token = base64.b64encode(
            json.dumps({"ts": time.time(), "errors": errors}).encode()
        ).decode()
        return json.dumps(
            {
                "status": "partial_success",
                "summary": summary,
                "counts": counts,
                "errors": clean_errors,
                "retry_token": retry_token,
            }
        )

    return json.dumps({"status": "success", "summary": summary, "counts": counts})
