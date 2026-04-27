"""Tests for handoff parser (lib/handoff.py).

Parses ``## Next Session Resumes Here`` block from session files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib.handoff import HandoffBlock, parse_handoff


@pytest.fixture()
def session_file(tmp_path: Path) -> Path:
    return tmp_path / "session-2026-04-27.md"


class TestParseHandoff:
    def test_absent_section_returns_none(self, session_file: Path) -> None:
        session_file.write_text("# Session: 2026-04-27\n\n## Key Decisions\n- Decided X\n")
        assert parse_handoff(session_file) is None

    def test_full_section_extracts_all_subsections(self, session_file: Path) -> None:
        session_file.write_text(
            "# Session: 2026-04-27\n"
            "\n"
            "## Key Decisions\n"
            "- Picked path D\n"
            "\n"
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "- Worked on todo 804 impl\n"
            "\n"
            "### Blocked\n"
            "- Waiting on user review\n"
            "\n"
            "### Next Action\n"
            "- Resume Task 3 of plan\n"
            "\n"
            "### Files / Todos\n"
            "- Todos: 804\n"
            "- Files: lib/handoff.py\n"
        )
        block = parse_handoff(session_file)
        assert block is not None
        assert "Worked on todo 804 impl" in block.attempted
        assert "Waiting on user review" in block.blocked
        assert "Resume Task 3 of plan" in block.next_action
        assert "Todos: 804" in block.files_todos
        assert "Files: lib/handoff.py" in block.files_todos

    def test_subsection_bodies_are_stripped(self, session_file: Path) -> None:
        session_file.write_text(
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "\n"
            "- Item 1\n"
            "\n"
            "### Blocked\n"
            "- Item 2\n"
            "\n"
            "\n"
            "### Next Action\n"
            "- Do thing\n"
            "\n"
            "### Files / Todos\n"
            "- Todos: x\n"
        )
        block = parse_handoff(session_file)
        assert block is not None
        assert block.attempted.startswith("- Item 1")
        assert not block.attempted.endswith("\n\n")
        assert block.blocked == "- Item 2"

    def test_placeholder_detection(self, session_file: Path) -> None:
        session_file.write_text(
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "- Did things\n"
            "\n"
            "### Blocked\n"
            "- _(none)_\n"
            "\n"
            "### Next Action\n"
            "- _(no concrete next action — review session or ask user)_\n"
            "\n"
            "### Files / Todos\n"
            "- _(none specified)_\n"
        )
        block = parse_handoff(session_file)
        assert block is not None
        assert not block.is_empty_placeholder("attempted")
        assert block.is_empty_placeholder("blocked")
        assert block.is_empty_placeholder("next_action")
        assert block.is_empty_placeholder("files_todos")

    def test_terminates_at_next_h2(self, session_file: Path) -> None:
        session_file.write_text(
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "- alpha\n"
            "\n"
            "### Blocked\n"
            "- _(none)_\n"
            "\n"
            "### Next Action\n"
            "- beta\n"
            "\n"
            "### Files / Todos\n"
            "- _(none specified)_\n"
            "\n"
            "## Open Questions\n"
            "- gamma\n"
        )
        block = parse_handoff(session_file)
        assert block is not None
        assert "gamma" not in block.files_todos
        assert "gamma" not in block.next_action
        assert "Open Questions" not in block.files_todos

    def test_terminates_at_eof(self, session_file: Path) -> None:
        session_file.write_text(
            "## Key Decisions\n"
            "- Foo\n"
            "\n"
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "- alpha\n"
            "\n"
            "### Blocked\n"
            "- _(none)_\n"
            "\n"
            "### Next Action\n"
            "- beta\n"
            "\n"
            "### Files / Todos\n"
            "- gamma\n"
        )
        block = parse_handoff(session_file)
        assert block is not None
        assert "gamma" in block.files_todos

    def test_preserves_markdown_including_nested_bullets(self, session_file: Path) -> None:
        session_file.write_text(
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "- top-level bullet\n"
            "  - nested bullet\n"
            "  - another nested\n"
            "    - deeply nested\n"
            "\n"
            "### Blocked\n"
            "- _(none)_\n"
            "\n"
            "### Next Action\n"
            "- Run `pytest` then commit.\n"
            "\n"
            "### Files / Todos\n"
            "- _(none specified)_\n"
        )
        block = parse_handoff(session_file)
        assert block is not None
        assert "  - nested bullet" in block.attempted
        assert "    - deeply nested" in block.attempted
        assert "`pytest`" in block.next_action

    def test_multiple_headings_first_wins(self, session_file: Path) -> None:
        session_file.write_text(
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "- first occurrence\n"
            "\n"
            "### Blocked\n"
            "- _(none)_\n"
            "\n"
            "### Next Action\n"
            "- first action\n"
            "\n"
            "### Files / Todos\n"
            "- first files\n"
            "\n"
            "## Some Other Section\n"
            "\n"
            "## Next Session Resumes Here\n"
            "\n"
            "### Attempted\n"
            "- second occurrence\n"
            "\n"
            "### Blocked\n"
            "- _(none)_\n"
            "\n"
            "### Next Action\n"
            "- second action\n"
            "\n"
            "### Files / Todos\n"
            "- second files\n"
        )
        block = parse_handoff(session_file)
        assert block is not None
        assert "first occurrence" in block.attempted
        assert "second occurrence" not in block.attempted
        assert "first action" in block.next_action
        assert "second action" not in block.next_action


class TestHandoffBlockDataclass:
    def test_is_frozen(self) -> None:
        block = HandoffBlock(attempted="a", blocked="b", next_action="c", files_todos="d")
        with pytest.raises((AttributeError, Exception)):
            block.attempted = "x"  # type: ignore[misc]
