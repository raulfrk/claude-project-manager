"""Context injection helpers: keyword extraction, relevance scoring, budget allocation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from server.lib import storage

if TYPE_CHECKING:
    from server.lib.models import JsonValue, ProjConfig, Todo

# ~80 common English stop words
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "not",
        "no",
        "nor",
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "our",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "if",
        "about",
        "up",
        "just",
        "also",
        "any",
        "because",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z]{2,}")


def _extract_keywords(
    todos: list[Todo],
    project_name: str,
    project_description: str,
    git_diff_paths: list[str],
) -> list[str]:
    """Extract deduplicated keywords from project context, weighting in-progress todos higher.

    Returns lowercase keywords in insertion order, stop words removed.
    """
    parts: list[str] = []

    # In-progress todos first (higher weight)
    for todo in todos:
        if todo.status == "in-progress":
            parts.append(todo.title)
    # Then remaining todos
    for todo in todos:
        if todo.status != "in-progress":
            parts.append(todo.title)

    parts.append(project_name)
    parts.append(project_description)

    # Split git paths on "/" before tokenizing
    for path in git_diff_paths:
        parts.extend(path.split("/"))

    raw_text = " ".join(parts)
    tokens = _TOKEN_RE.findall(raw_text)
    lowered = [t.lower() for t in tokens]
    filtered = [t for t in lowered if t not in STOP_WORDS]

    # Deduplicate preserving order
    return list(dict.fromkeys(filtered))


def _score_relevance(
    text: str,
    keywords: list[str],
    active_todo_ids: list[str] | None = None,
) -> float:
    """Score text relevance against keywords using term-frequency with dampening.

    Returns a float clamped to [0.0, 1.0].
    """
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return 0.0

    lowered = [t.lower() for t in tokens]
    keyword_set = frozenset(keywords)
    hits = sum(1 for t in lowered if t in keyword_set)

    raw_score = hits / len(lowered) if lowered else 0.0

    # Length dampening: short texts get penalized
    dampening = min(1.0, len(tokens) / 20)
    score = raw_score * dampening

    # Todo ID boost
    if active_todo_ids:
        for tid in active_todo_ids:
            pattern = re.escape(tid) + r"(?!\d)"
            if re.search(pattern, text):
                score += 0.3

    return min(1.0, max(0.0, score))


def _allocate_budget(total: int, sections: dict[str, int]) -> dict[str, int]:
    """Allocate a character budget across sections using the largest-remainder method.

    Args:
        total: Total budget to allocate.
        sections: Mapping of section name to weight (e.g. percentage).

    Returns:
        Mapping of section name to allocated budget (integers summing to total).
    """
    weight_sum = sum(sections.values())
    if weight_sum == 0:
        # Distribute equally if all weights are zero
        n = len(sections)
        if n == 0:
            return {}
        base = total // n
        result = dict.fromkeys(sections, base)
        # Give remainder to first section
        remainder = total - base * n
        for k in result:
            if remainder > 0:
                result[k] += 1
                remainder -= 1
        return result

    # Compute exact quotas
    quotas: dict[str, float] = {k: (v / weight_sum) * total for k, v in sections.items()}

    # Floor allocations
    floors: dict[str, int] = {k: math.floor(q) for k, q in quotas.items()}
    allocated = sum(floors.values())
    remainder = total - allocated

    # Sort by fractional remainder descending
    by_remainder = sorted(quotas.keys(), key=lambda k: quotas[k] - floors[k], reverse=True)
    for k in by_remainder:
        if remainder <= 0:
            break
        floors[k] += 1
        remainder -= 1

    return floors


def _truncate_to_budget(items: list[str], budget: int) -> list[str]:
    """Select items that fit within a character budget.

    If the last included item doesn't fully fit but has >10 chars remaining,
    it is truncated with "..." appended.

    Returns a list of items (possibly with the last one truncated).
    """
    result: list[str] = []
    used = 0

    for item in items:
        item_len = len(item)
        if used + item_len <= budget:
            result.append(item)
            used += item_len
        else:
            remaining = budget - used
            if remaining > 10:
                result.append(item[: remaining - 3] + "...")
            break

    return result


# ── Tiered injection ──────────────────────────────────────────────────────────

_DATE_HEADER_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")


@dataclass
class _TimestampedItem:
    text: str
    timestamp: datetime
    score: float = 0.0


@dataclass
class ContextInjection:
    notes: str = ""
    decisions: str = ""
    knowledge: str = ""
    total_chars: int = 0


def _parse_note_sections(raw: str) -> list[_TimestampedItem]:
    """Parse NOTES.md into timestamped items split by ``## YYYY-MM-DD`` headers."""
    items: list[_TimestampedItem] = []
    current_date: datetime | None = None
    current_lines: list[str] = []

    for line in raw.splitlines():
        match = _DATE_HEADER_RE.match(line)
        if match:
            # Flush previous section
            if current_date is not None and current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    items.append(_TimestampedItem(text=text, timestamp=current_date))
            current_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
            current_lines = []
        else:
            current_lines.append(line)

    # Flush last section
    if current_date is not None and current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            items.append(_TimestampedItem(text=text, timestamp=current_date))

    return items


def _format_decision(entry: dict[str, JsonValue]) -> str:
    """Format a decision entry as: **Decision** (YYYY-MM-DD): <text> [tags]."""
    ts = str(entry.get("timestamp", ""))
    # Extract date portion from ISO timestamp
    date_part = ts[:10] if len(ts) >= 10 else ts
    decision = str(entry.get("decision", ""))
    tags = entry.get("tags", [])
    tag_str = f" [{', '.join(str(t) for t in tags)}]" if tags and isinstance(tags, list) else ""
    ctx = str(entry.get("context", ""))
    ctx_str = f" -- {ctx}" if ctx else ""
    return f"**Decision** ({date_part}): {decision}{ctx_str}{tag_str}"


def _load_decision_items(cfg: ProjConfig, project_name: str) -> list[_TimestampedItem]:
    """Read decisions.yaml via storage, create _TimestampedItem list."""
    entries = storage.load_decisions(cfg, project_name)
    items: list[_TimestampedItem] = []
    for entry in entries:
        ts_str = str(entry.get("timestamp", ""))
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        except (ValueError, TypeError):
            # Fall back to date-only or skip
            try:
                ts = datetime.strptime(ts_str[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue
        text = _format_decision(entry)
        items.append(_TimestampedItem(text=text, timestamp=ts))
    return items


# ── Knowledge helpers ────────────────────────────────────────────────────────

_KNOWLEDGE_DATE_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")


def _read_all_knowledge(cfg: ProjConfig, project_name: str) -> list[_TimestampedItem]:
    """Parse knowledge.md and session-*.md ``## Project Knowledge`` sections.

    Returns _TimestampedItem list combining both sources.
    """
    items: list[_TimestampedItem] = []

    # --- knowledge.md (dated sections with bullet items) ---
    knowledge_path = storage.tracking_dir(cfg, project_name) / "knowledge.md"
    if knowledge_path.exists():
        content = knowledge_path.read_text()
        current_date: datetime | None = None
        current_lines: list[str] = []

        for line in content.splitlines():
            match = _KNOWLEDGE_DATE_RE.match(line)
            if match:
                # Flush previous section
                if current_date is not None and current_lines:
                    text = "\n".join(current_lines).strip()
                    if text:
                        items.append(_TimestampedItem(text=text, timestamp=current_date))
                current_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
                current_lines = []
            else:
                current_lines.append(line)

        # Flush last section
        if current_date is not None and current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                items.append(_TimestampedItem(text=text, timestamp=current_date))

    # --- session-*.md "## Project Knowledge" sections ---
    sessions_dir = storage.tracking_dir(cfg, project_name) / "sessions"
    if sessions_dir.is_dir():
        _SESSION_DATE_RE = re.compile(r"session-(\d{4}-\d{2}-\d{2})")
        for f in sorted(sessions_dir.glob("session-*.md")):
            date_match = _SESSION_DATE_RE.search(f.stem)
            if not date_match:
                continue
            try:
                file_date = datetime.strptime(date_match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            session_content = f.read_text()
            sections = re.split(r"(?=^## )", session_content, flags=re.MULTILINE)
            for section in sections:
                if section.startswith("## Project Knowledge"):
                    body = section.split("\n", 1)[1] if "\n" in section else ""
                    body = body.strip()
                    if body:
                        items.append(_TimestampedItem(text=body, timestamp=file_date))

    return items


def _is_duplicate(
    knowledge_text: str,
    injected_note_sections: list[str],
    threshold: float = 0.7,
    min_tokens: int = 5,
) -> bool:
    """Per-note-section comparison. Short items (<min_tokens tokens) bypass dedup."""
    tokens = _TOKEN_RE.findall(knowledge_text)
    if len(tokens) < min_tokens:
        return False

    knowledge_tokens = frozenset(t.lower() for t in tokens)

    for section in injected_note_sections:
        section_tokens = frozenset(t.lower() for t in _TOKEN_RE.findall(section))
        if not section_tokens:
            continue
        # Jaccard-like overlap: fraction of knowledge tokens present in section
        overlap = len(knowledge_tokens & section_tokens)
        denominator = min(len(knowledge_tokens), len(section_tokens))
        if denominator > 0 and overlap / denominator >= threshold:
            return True

    return False


def _inject_section_tiered(
    items: list[_TimestampedItem],
    budget: int,
    keywords: list[str],
    recency_hours: int,
    active_todo_ids: list[str] | None = None,
) -> str:
    """3-tier injection.

    - Tier 1 (recent): items within *recency_hours*, up to 50 % of budget.
    - Tier 2 (relevant): remaining items scored by keyword relevance, fill by score.
    - Tier 3 (fallback): most recent remaining items to fill budget.
    """
    if not items or budget <= 0:
        return ""

    now = datetime.now(tz=UTC)
    cutoff_seconds = recency_hours * 3600

    tier1: list[_TimestampedItem] = []
    rest: list[_TimestampedItem] = []

    for item in items:
        age = (now - item.timestamp).total_seconds()
        if age <= cutoff_seconds:
            tier1.append(item)
        else:
            rest.append(item)

    # Tier 1: most recent first, up to 50% of budget
    tier1.sort(key=lambda i: i.timestamp, reverse=True)
    tier1_budget = budget // 2
    tier1_texts = _truncate_to_budget([i.text for i in tier1], tier1_budget)
    tier1_used = sum(len(t) for t in tier1_texts)

    remaining_budget = budget - tier1_used

    # Score remaining items for tier 2
    for item in rest:
        item.score = _score_relevance(item.text, keywords, active_todo_ids)

    # Tier 2: by relevance score descending
    scored = sorted(rest, key=lambda i: i.score, reverse=True)
    tier2_texts: list[str] = []
    tier2_used = 0
    tier3_pool: list[_TimestampedItem] = []

    for item in scored:
        if item.score <= 0.0:
            tier3_pool.append(item)
            continue
        item_len = len(item.text)
        if tier2_used + item_len <= remaining_budget:
            tier2_texts.append(item.text)
            tier2_used += item_len
        elif remaining_budget - tier2_used > 10:
            space = remaining_budget - tier2_used
            tier2_texts.append(item.text[: space - 3] + "...")
            tier2_used += space
            tier3_pool.append(item)
            break
        else:
            tier3_pool.append(item)

    remaining_budget -= tier2_used

    # Tier 3: most recent remaining items
    tier3_pool.sort(key=lambda i: i.timestamp, reverse=True)
    tier3_texts = _truncate_to_budget([i.text for i in tier3_pool], remaining_budget)

    parts = tier1_texts + tier2_texts + tier3_texts
    return "\n\n".join(parts) if parts else ""


def inject_context(
    cfg: ProjConfig,
    project_name: str,
    todos: list[Todo],
    git_diff_paths: list[str],
) -> ContextInjection:
    """Main entry point for context injection.

    Checks ``cfg.context_injection.enabled``, allocates budget across sections,
    and calls :func:`_inject_section_tiered` per section.

    Populates notes, decisions, and knowledge sections with tiered injection.
    """
    ci_cfg = cfg.context_injection
    if not ci_cfg.enabled:
        return ContextInjection()

    # Extract keywords from project context
    keywords = _extract_keywords(
        todos=todos,
        project_name=project_name,
        project_description="",
        git_diff_paths=git_diff_paths,
    )

    active_todo_ids = [t.id for t in todos if t.status == "in-progress"]

    # Allocate budget across sections
    section_weights = {
        "notes": ci_cfg.sections.notes,
        "decisions": ci_cfg.sections.decisions,
        "knowledge": ci_cfg.sections.knowledge,
    }
    budgets = _allocate_budget(ci_cfg.budget, section_weights)

    # --- Notes ---
    raw_notes = storage.read_notes(cfg, project_name, max_chars=ci_cfg.budget * 2)
    note_items = _parse_note_sections(raw_notes)
    notes_text = _inject_section_tiered(
        items=note_items,
        budget=budgets.get("notes", 0),
        keywords=keywords,
        recency_hours=ci_cfg.recency_window,
        active_todo_ids=active_todo_ids,
    )

    # --- Decisions ---
    decision_items = _load_decision_items(cfg, project_name)
    decisions_text = _inject_section_tiered(
        items=decision_items,
        budget=budgets.get("decisions", 0),
        keywords=keywords,
        recency_hours=ci_cfg.recency_window,
        active_todo_ids=active_todo_ids,
    )

    # --- Knowledge ---
    knowledge_items = _read_all_knowledge(cfg, project_name)
    # Collect already-injected note section texts for dedup
    injected_note_sections = (
        [i.text for i in note_items if i.text in notes_text] if notes_text else []
    )
    # Filter out knowledge items that duplicate already-selected notes
    filtered_knowledge = [
        item for item in knowledge_items if not _is_duplicate(item.text, injected_note_sections)
    ]
    knowledge_text = _inject_section_tiered(
        items=filtered_knowledge,
        budget=budgets.get("knowledge", 0),
        keywords=keywords,
        recency_hours=ci_cfg.recency_window,
        active_todo_ids=active_todo_ids,
    )

    total = len(notes_text) + len(decisions_text) + len(knowledge_text)
    return ContextInjection(
        notes=notes_text,
        decisions=decisions_text,
        knowledge=knowledge_text,
        total_chars=total,
    )
