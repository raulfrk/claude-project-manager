"""Smoke tests for the claudemd subpackage shipped in claude-hook-transport."""

from __future__ import annotations

from pathlib import Path

import claudemd
from claudemd import (
    MANAGED_SECTION,
    MARKER_END,
    MARKER_START,
    ensure_managed_section,
    has_managed_section,
    remove_managed_section,
)
from claudemd import claudemd as _cm  # real module with the content file next to it


def test_claudemd_subpackage_loads():
    assert MANAGED_SECTION.startswith(MARKER_START)
    assert MANAGED_SECTION.endswith(MARKER_END)


class TestEnsureManagedSection:
    def test_creates_file_when_missing(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        result = ensure_managed_section(p)
        assert result is True
        assert p.exists()
        content = p.read_text()
        assert MARKER_START in content
        assert MARKER_END in content
        assert MANAGED_SECTION in content

    def test_appends_to_empty_file(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("")
        result = ensure_managed_section(p)
        assert result is True
        content = p.read_text()
        assert MANAGED_SECTION in content

    def test_appends_after_user_content(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        user_content = "# My Project\n\nSome notes.\n"
        p.write_text(user_content)
        result = ensure_managed_section(p)
        assert result is True
        content = p.read_text()
        assert content.startswith("# My Project")
        assert MANAGED_SECTION in content
        # User content preserved before the managed section
        assert content.index("# My Project") < content.index(MARKER_START)

    def test_replaces_existing_section(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        old_section = f"{MARKER_START}\nOld content here\n{MARKER_END}"
        p.write_text(f"# Header\n\n{old_section}\n")
        result = ensure_managed_section(p)
        assert result is True
        content = p.read_text()
        assert "Old content here" not in content
        assert MANAGED_SECTION in content
        assert content.startswith("# Header")

    def test_idempotent_returns_false(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        ensure_managed_section(p)
        result = ensure_managed_section(p)
        assert result is False

    def test_malformed_only_start_marker(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        p.write_text(f"# Header\n\n{MARKER_START}\nDangling start\n")
        result = ensure_managed_section(p)
        assert result is True
        content = p.read_text()
        # Should append a proper managed section (treats as absent)
        assert content.count(MARKER_END) >= 1
        assert MANAGED_SECTION in content

    def test_malformed_only_end_marker(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        p.write_text(f"# Header\n\nDangling end\n{MARKER_END}\n")
        result = ensure_managed_section(p)
        assert result is True
        content = p.read_text()
        assert MANAGED_SECTION in content


class TestRemoveManagedSection:
    def test_removes_existing_section(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        ensure_managed_section(p)
        result = remove_managed_section(p)
        assert result is True
        content = p.read_text()
        assert MARKER_START not in content
        assert MARKER_END not in content

    def test_no_markers_returns_false(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("# Just user content\n")
        result = remove_managed_section(p)
        assert result is False

    def test_missing_file_returns_false(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        result = remove_managed_section(p)
        assert result is False

    def test_preserves_user_content(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        user_content = "# My Project\n\nImportant notes.\n"
        p.write_text(user_content)
        ensure_managed_section(p)
        # Verify managed section was added
        assert MARKER_START in p.read_text()
        # Remove it
        remove_managed_section(p)
        content = p.read_text()
        assert "# My Project" in content
        assert "Important notes." in content
        assert MARKER_START not in content


class TestHasManagedSection:
    def test_with_markers(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        ensure_managed_section(p)
        assert has_managed_section(p) is True

    def test_without_markers(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("# No markers here\n")
        assert has_managed_section(p) is False

    def test_missing_file(self, tmp_path: Path):
        p = tmp_path / "CLAUDE.md"
        assert has_managed_section(p) is False


class TestManagedSectionContent:
    """Assert that MANAGED_SECTION contains required rule substrings."""

    def test_interactive_qa_mentions_ask_user_question(self):
        assert "AskUserQuestion" in MANAGED_SECTION

    def test_interactive_qa_mentions_multiple_choice(self):
        assert "multiple-choice" in MANAGED_SECTION

    def test_interactive_qa_mandates_batching(self):
        assert "batch" in MANAGED_SECTION
        assert "up to 4" in MANAGED_SECTION
        assert "extensive" in MANAGED_SECTION and "context" in MANAGED_SECTION

    def test_interactive_qa_mentions_open_ended_fallback(self):
        assert "open-ended" in MANAGED_SECTION
        assert "describe your goals" in MANAGED_SECTION

    def test_managed_section_contains_ask_user_question_batching_rule(self):
        assert "batch related questions into a single" in MANAGED_SECTION

    def test_task_usage_during_multi_step_work(self):
        assert "Task usage during multi-step work" in MANAGED_SECTION
        assert "TaskCreate" in MANAGED_SECTION
        assert "in_progress" in MANAGED_SECTION

    def test_task_status_accuracy(self):
        assert "Task status accuracy" in MANAGED_SECTION
        assert "NEVER mark a Task completed unless work is fully done" in MANAGED_SECTION

    def test_proj_todo_boundary(self):
        assert "Proj todo boundary" in MANAGED_SECTION
        assert "execution-time progress tracking" in MANAGED_SECTION
        assert "durable project state" in MANAGED_SECTION

    def test_sub_task_nesting(self):
        assert "Sub-task nesting" in MANAGED_SECTION
        assert "No depth cap" in MANAGED_SECTION
        assert "3-10 subtasks per agent" in MANAGED_SECTION

    def test_managed_section_still_has_preexisting_rules(self):
        # Regression: new rules must not delete old ones
        assert "run_in_background=true" in MANAGED_SECTION
        assert "plan mode" in MANAGED_SECTION
        assert "Auto-capture" in MANAGED_SECTION
        assert "Interactive Q&A" in MANAGED_SECTION


def test_managed_section_loaded_from_file():
    """MANAGED_SECTION loads from claudemd/managed_section.md at import time."""
    section_path = Path(_cm.__file__).parent / "managed_section.md"
    assert section_path.is_file(), "managed_section.md must ship with claudemd package"
    file_content = section_path.read_text(encoding="utf-8").rstrip("\n")
    assert file_content == claudemd.MANAGED_SECTION


def test_managed_section_file_shipped():
    """claudemd/managed_section.md ships with the claudemd (_shared) package."""
    pkg_root = Path(_cm.__file__).parent
    assert (pkg_root / "managed_section.md").is_file()


def test_managed_section_markers_at_boundaries():
    """Markers are the first and last lines of managed_section.md."""
    section_path = Path(_cm.__file__).parent / "managed_section.md"
    lines = section_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == claudemd.MARKER_START
    last_non_empty = next(ln for ln in reversed(lines) if ln.strip())
    assert last_non_empty == claudemd.MARKER_END


def test_managed_section_contains_revdiff_rule():
    """The revdiff-routed review bullet is present in MANAGED_SECTION."""
    assert "Revdiff-routed spec/plan review" in claudemd.MANAGED_SECTION
    assert 'enabledPlugins["revdiff@revdiff"]' in claudemd.MANAGED_SECTION
    assert "superpowers skill" in claudemd.MANAGED_SECTION
    assert (
        "falls back silently" in claudemd.MANAGED_SECTION
        or "fall back silently" in claudemd.MANAGED_SECTION
    )
