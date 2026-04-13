"""Tests for installer.claudemd — managed section CRUD for CLAUDE.md files."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.claudemd import (
    MANAGED_SECTION,
    MARKER_END,
    MARKER_START,
    ensure_managed_section,
    has_managed_section,
    remove_managed_section,
)


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
        assert "/proj:define" in MANAGED_SECTION
        assert "batch them into a single" in MANAGED_SECTION
        assert "specific application" in MANAGED_SECTION

    def test_n_distinct_agents_canonical_sentence_in_managed_section(self):
        canonical = (
            "When this skill specifies N review/check roles per target, "
            "spawn N individual agents \u2014 never combine multiple roles "
            "into a single agent."
        )
        assert canonical in MANAGED_SECTION

    def test_escalation_rule_in_managed_section(self):
        assert "escalation_needed" in MANAGED_SECTION
        assert "AskUserQuestion" in MANAGED_SECTION
        assert "Do NOT improvise" in MANAGED_SECTION

    def test_managed_section_still_has_preexisting_rules(self):
        # Regression: new rules must not delete old ones
        assert "run_in_background=true" in MANAGED_SECTION
        assert "plan mode" in MANAGED_SECTION
        assert "Auto-capture" in MANAGED_SECTION
        assert "Interactive Q&A" in MANAGED_SECTION
        assert "Define-phase question batching" in MANAGED_SECTION
        assert "N distinct agents per N roles" in MANAGED_SECTION
        assert "Escalation on plan gaps" in MANAGED_SECTION


# TODO: spawn-site edits for these tests land in separate worktrees
# (todo-522 for N-distinct-agents, todo-525 for escalation). Once all
# three worktrees merge to dev, remove the xfail markers and verify.
_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"
_N_AGENTS_CANONICAL = (
    "When this skill specifies N review/check roles per target, "
    "spawn N individual agents \u2014 never combine multiple roles "
    "into a single agent."
)
_ESCALATION_CANONICAL = (
    "On issue not covered by the plan: (1) detect, "
    "(2) SendMessage team-lead with issue details, "
    "(3) team-lead escalates to user via AskUserQuestion."
)


@pytest.mark.xfail(
    strict=False,
    reason="spawn-site edits land in todo-522 worktree",
)
@pytest.mark.parametrize(
    "skill_rel",
    [
        "proj/skills/refine/SKILL.md",
        "proj/skills/run/SKILL.md",
        "proj/skills/execute/SKILL.md",
        "proj/skills/decompose/SKILL.md",
    ],
)
def test_n_distinct_agents_rule_at_all_spawn_sites(skill_rel: str):
    skill_path = _PLUGINS_DIR / skill_rel
    content = skill_path.read_text(encoding="utf-8")
    # decompose may declare "not applicable" via an HTML comment
    if "decompose" in skill_rel and "<!-- N-agents rule: not applicable" in content:
        return
    assert _N_AGENTS_CANONICAL in content, (
        f"Canonical N-agents sentence missing in {skill_rel}"
    )


@pytest.mark.xfail(
    strict=False,
    reason="spawn-site edits land in todo-525 worktree",
)
def test_escalation_canonical_sentence_at_all_spawn_sites():
    run_path = _PLUGINS_DIR / "proj/skills/run/SKILL.md"
    execute_path = _PLUGINS_DIR / "proj/skills/execute/SKILL.md"
    run_content = run_path.read_text(encoding="utf-8")
    execute_content = execute_path.read_text(encoding="utf-8")
    assert run_content.count(_ESCALATION_CANONICAL) == 3, (
        "Expected 3 occurrences of escalation sentence in run/SKILL.md"
    )
    assert execute_content.count(_ESCALATION_CANONICAL) == 2, (
        "Expected 2 occurrences of escalation sentence in execute/SKILL.md"
    )
