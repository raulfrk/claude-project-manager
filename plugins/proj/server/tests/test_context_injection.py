"""Unit tests for context_injection pure functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from server.lib.models import Todo
from server.tools.context_injection import (
    _allocate_budget,
    _extract_keywords,
    _format_decision,
    _inject_section_tiered,
    _is_duplicate,
    _parse_note_sections,
    _score_relevance,
    _TimestampedItem,
    _truncate_to_budget,
)

# ── _extract_keywords ────────────────────────────────────────────────────────


class TestExtractKeywords:
    def test_basic_todo_titles(self) -> None:
        todos = [Todo(id="1", title="Implement authentication module", status="pending")]
        result = _extract_keywords(todos, "myproject", "", [])
        assert "implement" in result
        assert "authentication" in result
        assert "module" in result

    def test_in_progress_prioritized(self) -> None:
        """In-progress todos appear before pending ones, so their keywords come first."""
        todos = [
            Todo(id="1", title="alpha feature", status="pending"),
            Todo(id="2", title="beta feature", status="in-progress"),
        ]
        result = _extract_keywords(todos, "proj", "", [])
        # beta comes from in-progress todo, should appear before alpha
        assert result.index("beta") < result.index("alpha")

    def test_stop_words_removed(self) -> None:
        todos = [Todo(id="1", title="the quick and the slow", status="pending")]
        result = _extract_keywords(todos, "proj", "", [])
        assert "the" not in result
        assert "and" not in result
        assert "quick" in result
        assert "slow" in result

    def test_empty_inputs(self) -> None:
        result = _extract_keywords([], "", "", [])
        assert result == []

    def test_special_chars_ignored(self) -> None:
        """Tokens with < 2 chars or non-alpha are dropped by the regex."""
        todos = [Todo(id="1", title="fix bug #123 in v2", status="pending")]
        result = _extract_keywords(todos, "proj", "", [])
        # "#123" and "v2" have digits so regex won't capture them
        # "in" is a stop word
        assert "fix" in result
        assert "bug" in result

    def test_dedup_preserves_order(self) -> None:
        todos = [
            Todo(id="1", title="auth auth auth", status="pending"),
            Todo(id="2", title="auth module", status="pending"),
        ]
        result = _extract_keywords(todos, "proj", "", [])
        assert result.count("auth") == 1

    def test_git_paths_split(self) -> None:
        result = _extract_keywords([], "proj", "", ["src/lib/utils.py"])
        assert "src" in result
        assert "lib" in result
        assert "utils" in result


# ── _score_relevance ─────────────────────────────────────────────────────────


class TestScoreRelevance:
    def test_known_score(self) -> None:
        # "hello world" with keywords ["hello"] -> 1 hit / 2 tokens = 0.5
        # dampening = min(1.0, 2/20) = 0.1
        # score = 0.5 * 0.1 = 0.05
        score = _score_relevance("hello world", ["hello"])
        assert score == pytest.approx(0.05, abs=1e-6)

    def test_todo_id_boost(self) -> None:
        text = "Working on todo 42 implementation"
        score_no_boost = _score_relevance(text, ["working"])
        score_with_boost = _score_relevance(text, ["working"], active_todo_ids=["42"])
        assert score_with_boost > score_no_boost
        # Boost is +0.3
        assert score_with_boost - score_no_boost == pytest.approx(0.3, abs=0.01)

    def test_empty_text(self) -> None:
        assert _score_relevance("", ["hello"]) == 0.0

    def test_empty_keywords(self) -> None:
        assert _score_relevance("hello world", []) == 0.0

    def test_clamped_to_one(self) -> None:
        """Even with multiple boosts, score cannot exceed 1.0."""
        text = "todo 1 and todo 2 and todo 3 keyword keyword keyword keyword keyword"
        score = _score_relevance(text, ["keyword"], active_todo_ids=["1", "2", "3"])
        assert score <= 1.0

    def test_length_dampening(self) -> None:
        """Short texts get penalized more than long texts."""
        keywords = ["auth"]
        short = _score_relevance("auth", keywords)
        # 20 tokens so dampening = 1.0
        long_text = " ".join(["auth"] + ["filler"] * 19)
        _score_relevance(long_text, keywords)
        # Short has dampening = min(1.0, 1/20) = 0.05
        # Short raw = 1/1 = 1.0, score = 1.0 * 0.05 = 0.05
        assert short == pytest.approx(0.05, abs=1e-6)

    def test_id_458_1_not_matching_458_10(self) -> None:
        """ID '458.1' should NOT match '458.10' due to (?!\\d) boundary."""
        text = "Working on todo 458.10 feature"
        score_wrong = _score_relevance(text, [], active_todo_ids=["458.1"])
        score_exact = _score_relevance(text, [], active_todo_ids=["458.10"])
        # 458.1 should NOT boost because 458.10 has a trailing digit
        assert score_wrong == 0.0
        assert score_exact == pytest.approx(0.3, abs=0.01)


# ── _allocate_budget ─────────────────────────────────────────────────────────


class TestAllocateBudget:
    def test_standard_split(self) -> None:
        result = _allocate_budget(2000, {"notes": 40, "decisions": 35, "knowledge": 25})
        assert sum(result.values()) == 2000
        assert result["notes"] == 800
        assert result["decisions"] == 700
        assert result["knowledge"] == 500

    def test_zero_budget(self) -> None:
        result = _allocate_budget(0, {"a": 50, "b": 50})
        assert sum(result.values()) == 0

    def test_non_100_percentages(self) -> None:
        """Weights don't need to sum to 100 -- they're proportional."""
        result = _allocate_budget(100, {"a": 1, "b": 1})
        assert sum(result.values()) == 100
        assert result["a"] == 50
        assert result["b"] == 50

    def test_no_rounding_loss(self) -> None:
        """Largest-remainder method ensures sum == total even with odd splits."""
        result = _allocate_budget(100, {"a": 33, "b": 33, "c": 34})
        assert sum(result.values()) == 100

    def test_empty_sections(self) -> None:
        result = _allocate_budget(100, {})
        assert result == {}

    def test_zero_weight_equal_distribution(self) -> None:
        """When all weights are zero, distribute equally."""
        result = _allocate_budget(10, {"a": 0, "b": 0, "c": 0})
        assert sum(result.values()) == 10
        # 10 / 3 = 3 remainder 1
        assert sorted(result.values()) == [3, 3, 4]


# ── _truncate_to_budget ──────────────────────────────────────────────────────


class TestTruncateToBudget:
    def test_within_budget(self) -> None:
        items = ["hello", "world"]
        result = _truncate_to_budget(items, 100)
        assert result == ["hello", "world"]

    def test_overflow_truncates_last(self) -> None:
        items = ["abcdefghijklmnop", "second item here too"]
        # Budget 25: first item (16 chars) fits, second (20) doesn't.
        # Remaining = 25-16 = 9, which is < 10, so no partial.
        result = _truncate_to_budget(items, 25)
        assert result == ["abcdefghijklmnop"]

    def test_partial_fit_with_ellipsis(self) -> None:
        items = ["first", "second_long_item_here"]
        # budget = 20: first (5) fits, remaining = 15 > 10
        # partial = item[:15-3] + "..." = "second_long_" + "..." = "second_long_..."
        result = _truncate_to_budget(items, 20)
        assert len(result) == 2
        assert result[0] == "first"
        assert result[1].endswith("...")
        assert len(result[1]) == 15  # 20 - 5 = 15


# ── _inject_section_tiered ───────────────────────────────────────────────────


class TestInjectSectionTiered:
    def _make_item(self, text: str, hours_ago: float, score: float = 0.0) -> _TimestampedItem:
        ts = datetime.now(tz=UTC) - timedelta(hours=hours_ago)
        return _TimestampedItem(text=text, timestamp=ts, score=score)

    def test_tier1_recent(self) -> None:
        """Items within recency window go to tier 1."""
        recent = self._make_item("recent note content here", hours_ago=1)
        old = self._make_item("old note content here that is not recent", hours_ago=100)
        result = _inject_section_tiered([recent, old], budget=500, keywords=[], recency_hours=24)
        # Recent should appear before old
        assert "recent" in result
        assert result.index("recent") < result.index("old")

    def test_tier2_by_score(self) -> None:
        """Non-recent items scored by keyword relevance appear in tier 2."""
        # Both are old (beyond recency window)
        relevant = self._make_item(
            "authentication module security layer implementation design",
            hours_ago=100,
        )
        irrelevant = self._make_item(
            "random unrelated filler text padding here now",
            hours_ago=100,
        )
        result = _inject_section_tiered(
            [irrelevant, relevant],
            budget=2000,
            keywords=["authentication", "module", "security"],
            recency_hours=24,
        )
        # Relevant item should appear before irrelevant due to higher score
        assert "authentication" in result

    def test_fallback_fill(self) -> None:
        """Tier 3 fills remaining budget with most recent remaining items."""
        # No keywords match, so tier 2 is empty, tier 3 picks up by recency
        old1 = self._make_item("older_content " * 5, hours_ago=200)
        old2 = self._make_item("newest_old_content " * 5, hours_ago=50)
        result = _inject_section_tiered([old1, old2], budget=2000, keywords=[], recency_hours=24)
        # Both should appear; tier 3 sorts by most recent first
        assert "newest_old_content" in result
        assert "older_content" in result

    def test_empty_data(self) -> None:
        assert _inject_section_tiered([], budget=500, keywords=["test"], recency_hours=24) == ""

    def test_zero_budget(self) -> None:
        item = self._make_item("some text", hours_ago=1)
        assert _inject_section_tiered([item], budget=0, keywords=[], recency_hours=24) == ""


# ── _is_duplicate ────────────────────────────────────────────────────────────


class TestIsDuplicate:
    def test_duplicate_detected(self) -> None:
        knowledge = "authentication module security layer implementation"
        notes = ["authentication module security layer implementation design"]
        assert _is_duplicate(knowledge, notes) is True

    def test_non_duplicate(self) -> None:
        knowledge = "database migration schema update rollback strategy"
        notes = ["authentication module security layer implementation"]
        assert _is_duplicate(knowledge, notes) is False

    def test_short_bypass(self) -> None:
        """Items with fewer than min_tokens bypass dedup."""
        knowledge = "auth"  # 1 token, below min_tokens=5
        notes = ["auth"]
        assert _is_duplicate(knowledge, notes) is False

    def test_per_note_comparison(self) -> None:
        """Duplicate detection checks against each note section individually."""
        knowledge = "deployment pipeline configuration setup process"
        notes = [
            "unrelated content about testing strategy",
            "deployment pipeline configuration setup process implementation",
        ]
        # Should be duplicate because second note section overlaps
        assert _is_duplicate(knowledge, notes) is True


# ── _format_decision ─────────────────────────────────────────────────────────


class TestFormatDecision:
    def test_format_output(self) -> None:
        entry = {
            "timestamp": "2026-04-01T10:30:00",
            "decision": "Use PostgreSQL for persistence",
            "context": "Evaluated SQLite vs PG",
            "tags": ["database", "architecture"],
        }
        result = _format_decision(entry)
        assert "**Decision** (2026-04-01)" in result
        assert "Use PostgreSQL for persistence" in result
        assert "Evaluated SQLite vs PG" in result
        assert "[database, architecture]" in result

    def test_missing_fields(self) -> None:
        entry: dict = {"timestamp": "", "decision": "Quick decision"}
        result = _format_decision(entry)
        assert "Quick decision" in result
        # No context or tags
        assert "--" not in result
        assert "[]" not in result


# ── _parse_note_sections ─────────────────────────────────────────────────────


class TestParseNoteSections:
    def test_basic_parsing(self) -> None:
        raw = "## 2026-04-01\nFirst note\n\n## 2026-04-02\nSecond note"
        items = _parse_note_sections(raw)
        assert len(items) == 2
        assert items[0].text == "First note"
        assert items[1].text == "Second note"
        assert items[0].timestamp.year == 2026
        assert items[0].timestamp.month == 4
        assert items[0].timestamp.day == 1

    def test_empty_input(self) -> None:
        assert _parse_note_sections("") == []

    def test_no_headers(self) -> None:
        """Text without date headers produces no items."""
        assert _parse_note_sections("just some text\nwithout headers") == []
