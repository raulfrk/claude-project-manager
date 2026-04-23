"""Tests for lib/frontmatter.py."""

import pytest

from server.lib.frontmatter import FrontmatterError, dump, parse


class TestParse:
    def test_parse_valid(self) -> None:
        raw = "---\ntitle: Hooks\ntags: [a, b]\n---\n# Body\n\nContent."
        fm, body = parse(raw)
        assert fm == {"title": "Hooks", "tags": ["a", "b"]}
        assert body == "# Body\n\nContent."

    def test_parse_no_frontmatter(self) -> None:
        raw = "# No frontmatter here\n\nJust body."
        fm, body = parse(raw)
        assert fm == {}
        assert body == raw

    def test_parse_empty_frontmatter(self) -> None:
        raw = "---\n---\n# Body"
        fm, body = parse(raw)
        assert fm == {}
        assert body == "# Body"

    def test_parse_missing_closing_delim(self) -> None:
        raw = "---\ntitle: Hooks\n# missing close\n"
        with pytest.raises(FrontmatterError, match="unterminated frontmatter"):
            parse(raw)

    def test_parse_invalid_yaml(self) -> None:
        raw = "---\ntitle: : :\n---\nbody"
        with pytest.raises(FrontmatterError, match="invalid YAML"):
            parse(raw)

    def test_parse_preserves_body_leading_whitespace(self) -> None:
        raw = "---\ntitle: X\n---\n\n\nBody with leading newlines"
        fm, body = parse(raw)
        assert fm == {"title": "X"}
        # Exactly 2 leading newlines preserved (the blank line after --- + one more)
        assert body == "\n\nBody with leading newlines"


class TestDump:
    def test_dump_roundtrip(self) -> None:
        raw = "---\ntitle: Hooks\ntags:\n- a\n- b\n---\nBody."
        fm, body = parse(raw)
        redumped = dump(fm, body)
        fm2, body2 = parse(redumped)
        assert fm == fm2
        assert body.strip() == body2.strip()

    def test_dump_empty_frontmatter(self) -> None:
        result = dump({}, "just body")
        # No frontmatter when empty → body only
        assert result == "just body"

    def test_dump_with_body(self) -> None:
        result = dump({"title": "X"}, "body text")
        fm, body = parse(result)
        assert fm == {"title": "X"}
        assert body == "body text"
