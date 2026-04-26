"""Test that /proj:save SKILL.md step 11 invokes the new filter tool."""

from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "save" / "SKILL.md"


def test_skill_calls_wiki_ingest_filter_session() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    assert "mcp__proj__wiki_ingest_filter_session" in content


def test_skill_uses_tmp_path_for_subagent_source() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    # tmp_path returned by the tool must be substituted into {source}
    assert "tmp_path" in content
    # Cleanup language must mention deleting the tmp file
    assert "tmp" in content.lower() and (
        "delete" in content.lower() or "unlink" in content.lower() or "rm " in content.lower()
    )


def test_skill_declares_new_tool_in_allowed_tools() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    # Frontmatter `allowed-tools:` must include the new tool
    assert "mcp__proj__wiki_ingest_filter_session" in content.split("---", 2)[1]
