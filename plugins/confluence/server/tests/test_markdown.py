"""Tests for HTML-to-Markdown conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib.markdown import html_to_markdown

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("index", ["01", "02", "03", "04"])
def test_markdown_conversion(index: str) -> None:
    html = (FIXTURES_DIR / f"sample_view_{index}.html").read_text()
    expected = (FIXTURES_DIR / f"expected_md_{index}.md").read_text().strip()

    result = html_to_markdown(html).strip()

    def norm(s: str) -> str:
        return "\n".join(line.rstrip() for line in s.splitlines())

    msg = f"fixture {index}:\nExpected:\n{expected}\nGot:\n{result}"
    assert norm(result) == norm(expected), msg


def test_script_tags_stripped() -> None:
    html = "<p>hello</p><script>alert(1)</script>"
    result = html_to_markdown(html)
    assert "alert" not in result
    assert "hello" in result


def test_style_tags_stripped() -> None:
    html = "<style>body{color:red}</style><p>hi</p>"
    result = html_to_markdown(html)
    assert "color:red" not in result
    assert "hi" in result


def test_empty_input_returns_empty() -> None:
    assert html_to_markdown("") == ""
