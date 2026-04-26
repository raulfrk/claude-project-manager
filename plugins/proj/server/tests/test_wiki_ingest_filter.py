"""Tests for wiki_ingest_filter pure function."""

from __future__ import annotations

from server.lib.wiki_ingest_filter import filter_session_text


class TestSectionStrip:
    def test_strip_todos_worked_on_section(self) -> None:
        text = (
            "## Key Decisions\n"
            "- Decided X\n"
            "\n"
            "## Todos Worked On\n"
            "- 736: completed\n"
            "- 737: in progress\n"
            "\n"
            "## Insights Discovered\n"
            "- Insight A\n"
        )
        out = filter_session_text(text)
        assert "## Todos Worked On" not in out
        assert "736: completed" not in out
        assert "## Key Decisions" in out
        assert "Decided X" in out
        assert "## Insights Discovered" in out
        assert "Insight A" in out

    def test_strip_todos_worked_on_at_eof(self) -> None:
        text = "## Key Decisions\n- Decided X\n\n## Todos Worked On\n- 736: completed\n"
        out = filter_session_text(text)
        assert "## Todos Worked On" not in out
        assert "736: completed" not in out
        assert "## Key Decisions" in out

    def test_no_todos_section_no_change_to_sections(self) -> None:
        text = "## Key Decisions\n- Decided X\n\n## Insights Discovered\n- Insight A\n"
        out = filter_session_text(text)
        assert "## Key Decisions" in out
        assert "## Insights Discovered" in out


class TestTodoIdStrip:
    def test_strip_todo_id_explicit(self) -> None:
        text = "Continued work on todo 736 today.\nUnrelated line.\n"
        out = filter_session_text(text)
        assert "todo 736" not in out
        assert "Unrelated line." in out

    def test_strip_todo_id_with_dash(self) -> None:
        text = "todo-736 was completed.\nUnrelated.\n"
        out = filter_session_text(text)
        assert "todo-736" not in out
        assert "Unrelated." in out

    def test_strip_todo_id_case_insensitive(self) -> None:
        text = "TODO 999 needs attention.\nKeep me.\n"
        out = filter_session_text(text)
        assert "TODO 999" not in out
        assert "Keep me." in out

    def test_strip_bare_id_with_action_verb(self) -> None:
        text = "Closed 736 yesterday.\nKeep me.\n"
        out = filter_session_text(text)
        assert "Closed 736" not in out
        assert "Keep me." in out

    def test_keep_bare_id_without_action_verb(self) -> None:
        text = "File main.py:736 has the bug.\n"
        out = filter_session_text(text)
        assert "main.py:736" in out


class TestStatusPhraseStrip:
    def test_strip_in_flight(self) -> None:
        text = "This work is in-flight.\nKeep this.\n"
        out = filter_session_text(text)
        assert "in-flight" not in out
        assert "Keep this." in out

    def test_strip_active_improvement_axis(self) -> None:
        text = "The active improvement axis here is robustness.\nKeep this.\n"
        out = filter_session_text(text)
        assert "active improvement axis" not in out
        assert "Keep this." in out

    def test_strip_shipped_this_session(self) -> None:
        text = "Shipped this session: feature X.\nKeep this.\n"
        out = filter_session_text(text)
        assert "Shipped this session" not in out
        assert "Keep this." in out

    def test_strip_ready_to_start(self) -> None:
        text = "Items ready to start include A.\nKeep this.\n"
        out = filter_session_text(text)
        assert "ready to start" not in out
        assert "Keep this." in out

    def test_strip_blocked_on(self) -> None:
        text = "Currently blocked on dep Y.\nKeep this.\n"
        out = filter_session_text(text)
        assert "blocked on" not in out
        assert "Keep this." in out

    def test_strip_in_progress(self) -> None:
        text = "Work in progress on Z.\nKeep this.\n"
        out = filter_session_text(text)
        assert "in progress" not in out
        assert "Keep this." in out

    def test_strip_currently_working(self) -> None:
        text = "Currently working on W.\nKeep this.\n"
        out = filter_session_text(text)
        assert "currently working" not in out
        assert "Keep this." in out


class TestPreservesContent:
    def test_preserves_decisions_section(self) -> None:
        text = "## Key Decisions\n- Picked path D over A.\n- Reason: lower friction.\n"
        out = filter_session_text(text)
        assert out == text

    def test_preserves_concept_paragraph(self) -> None:
        text = (
            "PYTHONPATH plugin loading sidesteps namespace collision because\n"
            "start.sh execs the shared venv python directly with PYTHONPATH=$DIR.\n"
        )
        out = filter_session_text(text)
        assert out == text

    def test_preserves_evidence_refs(self) -> None:
        text = "Path D was chosen — commit b7dae45 lifted the lib.\n"
        out = filter_session_text(text)
        assert out == text
