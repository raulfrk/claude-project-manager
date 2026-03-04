"""Tests for the extract-todos skill regex and metadata parsing logic.

These tests directly exercise the regex pattern and metadata-parsing algorithm
defined in plugins/proj/skills/extract-todos/SKILL.md, using Python's re module.
No MCP server calls are made; this is pure unit-level coverage.
"""

from __future__ import annotations

import re

import pytest

# ---------------------------------------------------------------------------
# Pattern under test (copied verbatim from SKILL.md)
# ---------------------------------------------------------------------------

PATTERN = re.compile(r"(?i)\b(TODO|FIXME)\s*(?:\(([^)]*)\))?\s*:\s*(.*)")


def parse_metadata(raw_meta: str) -> dict[str, str]:
    """Metadata-parsing logic from SKILL.md Step 4."""
    meta: dict[str, str] = {}
    for part in raw_meta.split(","):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta


def map_priority(meta: dict[str, str]) -> str:
    """Priority mapping from SKILL.md Step 4 — invalid/absent → medium."""
    raw = meta.get("priority", "").lower()
    if raw in {"high", "medium", "low"}:
        return raw
    return "medium"


def extract_match(line: str):
    """Return (prefix, raw_meta, title) or None if no match."""
    m = PATTERN.search(line)
    if m is None:
        return None
    return m.group(1).upper(), m.group(2) or "", m.group(3).strip()


# ===========================================================================
# Regex matching tests
# ===========================================================================


class TestRegexMatching:
    def test_simple_todo(self):
        """# TODO: simple comment → title='simple comment', no metadata."""
        result = extract_match("# TODO: simple comment")
        assert result is not None
        prefix, raw_meta, title = result
        assert prefix == "TODO"
        assert title == "simple comment"
        assert raw_meta == ""

    def test_simple_fixme(self):
        """// FIXME: another comment → title='another comment'."""
        result = extract_match("// FIXME: another comment")
        assert result is not None
        prefix, raw_meta, title = result
        assert prefix == "FIXME"
        assert title == "another comment"
        assert raw_meta == ""

    def test_todo_with_full_metadata(self):
        """TODO(owner: Alice, priority: high, due: 2026-06-01): fix this thing."""
        line = "TODO(owner: Alice, priority: high, due: 2026-06-01): fix this thing"
        result = extract_match(line)
        assert result is not None
        prefix, raw_meta, title = result
        assert prefix == "TODO"
        assert title == "fix this thing"
        meta = parse_metadata(raw_meta)
        assert map_priority(meta) == "high"
        assert meta.get("owner") == "Alice"
        assert meta.get("due") == "2026-06-01"
        # owner tag construction
        assert f"owner:{meta['owner']}" == "owner:Alice"

    def test_case_insensitive_todo_lowercase(self):
        """todo: lower case keyword must match."""
        result = extract_match("todo: lower case keyword")
        assert result is not None
        prefix, _, title = result
        assert prefix == "TODO"
        assert title == "lower case keyword"

    def test_case_insensitive_fixme_lowercase(self):
        """fixme: lower case keyword must match."""
        result = extract_match("fixme: lower case keyword")
        assert result is not None
        prefix, _, title = result
        assert prefix == "FIXME"

    def test_case_insensitive_todo_mixed_case(self):
        """Todo: mixed case keyword must match."""
        result = extract_match("Todo: mixed case keyword")
        assert result is not None
        _, _, title = result
        assert title == "mixed case keyword"

    def test_no_match_plain_comment(self):
        """A regular comment without TODO/FIXME must not match."""
        result = extract_match("# This is just a regular comment")
        assert result is None

    def test_no_match_empty_line(self):
        result = extract_match("")
        assert result is None

    def test_empty_title_after_prefix(self):
        """TODO with no text after the colon should yield an empty title."""
        result = extract_match("# TODO:   ")
        assert result is not None
        _, _, title = result
        # The skill skips matches where title is empty after strip.
        assert title == ""

    def test_todo_inline_in_code(self):
        """TODO embedded inside a code line should still match (word boundary)."""
        result = extract_match("x = 1  # TODO: refactor this")
        assert result is not None
        _, _, title = result
        assert title == "refactor this"

    def test_fixme_with_priority_invalid(self):
        """FIXME(priority: invalid): bad priority defaults to medium."""
        line = "FIXME(priority: invalid): bad priority defaults to medium"
        result = extract_match(line)
        assert result is not None
        _, raw_meta, title = result
        meta = parse_metadata(raw_meta)
        assert map_priority(meta) == "medium"
        assert title == "bad priority defaults to medium"

    def test_no_space_before_colon(self):
        """TODO: with no trailing space after colon should still capture title."""
        result = extract_match("TODO:no space after colon")
        assert result is not None
        _, _, title = result
        assert title == "no space after colon"

    def test_multiple_colons_in_title(self):
        """Title may contain colons; only the first colon is the separator."""
        result = extract_match("# TODO: use format HH:MM:SS")
        assert result is not None
        _, _, title = result
        assert title == "use format HH:MM:SS"

    def test_fixme_no_word_boundary_inside_word(self):
        """AFIXME: should NOT match because there is no word boundary before FIXME."""
        result = extract_match("AFIXME: this should not match")
        assert result is None

    def test_todo_no_word_boundary_inside_word(self):
        """ATODO: should NOT match."""
        result = extract_match("ATODO: this should not match")
        assert result is None


# ===========================================================================
# Metadata parsing tests
# ===========================================================================


class TestMetadataParsing:
    def test_owner_priority_due(self):
        raw = "owner: Alice, priority: high, due: 2026-06-01"
        meta = parse_metadata(raw)
        assert meta == {"owner": "Alice", "priority": "high", "due": "2026-06-01"}

    def test_empty_raw_meta(self):
        assert parse_metadata("") == {}

    def test_unrecognized_keys_are_parsed_but_ignored_by_skill(self):
        """Keys like 'assigned' are parsed into meta but ignored when building todo."""
        raw = "assigned: Bob, priority: low"
        meta = parse_metadata(raw)
        # Key is present in the dict but the skill never reads 'assigned'.
        assert meta.get("assigned") == "Bob"
        # Recognized fields still work.
        assert map_priority(meta) == "low"
        # No 'owner' key so no owner tag is added.
        assert "owner" not in meta

    def test_priority_high(self):
        meta = parse_metadata("priority: high")
        assert map_priority(meta) == "high"

    def test_priority_medium(self):
        meta = parse_metadata("priority: medium")
        assert map_priority(meta) == "medium"

    def test_priority_low(self):
        meta = parse_metadata("priority: low")
        assert map_priority(meta) == "low"

    def test_priority_absent_defaults_to_medium(self):
        meta = parse_metadata("owner: Carol")
        assert map_priority(meta) == "medium"

    def test_priority_invalid_defaults_to_medium(self):
        meta = parse_metadata("priority: critical")
        assert map_priority(meta) == "medium"

    def test_priority_case_insensitive_after_lower(self):
        """The SKILL.md code lowercases the value, so 'HIGH' should map to high."""
        # parse_metadata stores the raw value; map_priority calls .lower() itself.
        meta = parse_metadata("priority: HIGH")
        assert map_priority(meta) == "high"

    def test_value_with_colon_inside(self):
        """A value like 'due: 2026-06-01' has a colon; split(..., 1) handles it."""
        raw = "due: 2026-06-01"
        meta = parse_metadata(raw)
        assert meta.get("due") == "2026-06-01"

    def test_extra_whitespace_around_parts(self):
        raw = "  owner :  Alice  ,  priority : high  "
        meta = parse_metadata(raw)
        assert meta.get("owner") == "Alice"
        assert map_priority(meta) == "high"

    def test_single_key(self):
        meta = parse_metadata("priority: low")
        assert meta == {"priority": "low"}

    def test_part_without_colon_is_skipped(self):
        """A comma-delimited part with no colon must be silently ignored."""
        raw = "priority: high, badpart, owner: Bob"
        meta = parse_metadata(raw)
        assert "badpart" not in meta
        assert meta.get("priority") == "high"
        assert meta.get("owner") == "Bob"


# ===========================================================================
# End-to-end flow tests (regex + metadata + priority mapping)
# ===========================================================================


class TestEndToEndFlow:
    def _process_line(self, line: str):
        """Simulate the skill's per-line processing logic."""
        result = extract_match(line)
        if result is None:
            return None
        prefix, raw_meta, title = result
        if not title:
            return None  # skip empty titles
        meta = parse_metadata(raw_meta)
        priority = map_priority(meta)
        owner = meta.get("owner")
        due_date = meta.get("due") or None
        tags = [f"owner:{owner}"] if owner else []
        return {
            "prefix": prefix,
            "title": title,
            "priority": priority,
            "tags": tags,
            "due_date": due_date,
        }

    def test_simple_todo_no_metadata(self):
        record = self._process_line("# TODO: simple comment")
        assert record is not None
        assert record["title"] == "simple comment"
        assert record["priority"] == "medium"
        assert record["tags"] == []
        assert record["due_date"] is None

    def test_fixme_no_metadata(self):
        record = self._process_line("// FIXME: another comment")
        assert record is not None
        assert record["title"] == "another comment"
        assert record["prefix"] == "FIXME"

    def test_full_metadata_record(self):
        line = "TODO(owner: Alice, priority: high, due: 2026-06-01): fix this thing"
        record = self._process_line(line)
        assert record is not None
        assert record["title"] == "fix this thing"
        assert record["priority"] == "high"
        assert record["tags"] == ["owner:Alice"]
        assert record["due_date"] == "2026-06-01"

    def test_invalid_priority_yields_medium(self):
        line = "FIXME(priority: invalid): bad priority defaults to medium"
        record = self._process_line(line)
        assert record is not None
        assert record["priority"] == "medium"

    def test_empty_title_is_skipped(self):
        record = self._process_line("# TODO:   ")
        assert record is None

    def test_unrecognized_key_ignored(self):
        line = "TODO(assigned: Bob, priority: low): do something"
        record = self._process_line(line)
        assert record is not None
        assert record["tags"] == []  # 'assigned' is not 'owner'
        assert record["priority"] == "low"

    def test_no_match_returns_none(self):
        record = self._process_line("# just a normal comment")
        assert record is None

    def test_case_insensitive_todo(self):
        for kw in ("todo", "Todo", "TODO", "tOdO"):
            record = self._process_line(f"{kw}: some task")
            assert record is not None, f"Expected match for keyword '{kw}'"
            assert record["prefix"] == "TODO"

    def test_case_insensitive_fixme(self):
        for kw in ("fixme", "Fixme", "FIXME", "fIxMe"):
            record = self._process_line(f"{kw}: some task")
            assert record is not None, f"Expected match for keyword '{kw}'"
            assert record["prefix"] == "FIXME"
