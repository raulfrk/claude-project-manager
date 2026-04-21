"""HTML-to-Markdown conversion for Confluence view format."""

from __future__ import annotations

from bs4 import BeautifulSoup
from markdownify import markdownify as _md


def html_to_markdown(html: str) -> str:
    """Convert Confluence view-format HTML to Markdown."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return _md(
        str(soup),
        heading_style="ATX",
        bullets="-",
        code_language="",
    ).strip()
