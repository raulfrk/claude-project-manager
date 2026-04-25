"""Tests for tier-2 section_map drift detection (check_section_map_drift)."""

from __future__ import annotations

from pathlib import Path

from server.tools.lint import _extract_save_skill_h2s, check_section_map_drift

# ---------------------------------------------------------------------------
# Synthetic SKILL.md fixture helpers
# ---------------------------------------------------------------------------

_SKILL_TEMPLATE = """\
---
name: save
---

**7.** Write session file via Write tool to path:

   ```
   # Session: <date>

   ## User Note
   <only if user provided something>

   ## Key Decisions
   - <bullet>

   ## Todos Worked On
   - <bullet with todo ID and outcome>

   ## Insights Discovered
   - <bullet>

   ## Open Questions
   - <bullet>
   ```

**8.** Knowledge bridge.
"""

_SKILL_TEMPLATE_TWO_HEADINGS = """\
---
name: save
---

**7.** Write session file:

   ```
   # Session: <date>

   ## Key Decisions
   - <bullet>

   ## Insights Discovered
   - <bullet>
   ```

**8.** Done.
"""

_SKILL_NO_STEP7 = """\
---
name: save
---

This SKILL has no step 7 anchor at all.
"""


# ---------------------------------------------------------------------------
# Unit tests for _extract_save_skill_h2s
# ---------------------------------------------------------------------------


class TestExtractSaveSkillH2s:
    def test_extracts_h2s_from_template_block(self) -> None:
        h2s = _extract_save_skill_h2s(_SKILL_TEMPLATE)
        assert h2s == [
            "User Note",
            "Key Decisions",
            "Todos Worked On",
            "Insights Discovered",
            "Open Questions",
        ]

    def test_extracts_two_headings(self) -> None:
        h2s = _extract_save_skill_h2s(_SKILL_TEMPLATE_TWO_HEADINGS)
        assert h2s == ["Key Decisions", "Insights Discovered"]

    def test_no_step7_anchor_returns_empty(self) -> None:
        h2s = _extract_save_skill_h2s(_SKILL_NO_STEP7)
        assert h2s == []

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_save_skill_h2s("") == []


# ---------------------------------------------------------------------------
# Unit tests for check_section_map_drift
# ---------------------------------------------------------------------------


class TestCheckSectionMapDrift:
    def test_skill_path_none_returns_not_found_warning(self) -> None:
        warnings = check_section_map_drift(None, {"Key Decisions": "decisions"})
        assert len(warnings) == 1
        assert warnings[0]["kind"] == "skill_not_found"
        assert "Could not locate" in warnings[0]["message"]

    def test_skill_path_missing_file_returns_not_found_warning(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent" / "SKILL.md"
        warnings = check_section_map_drift(missing, {"Key Decisions": "decisions"})
        assert len(warnings) == 1
        assert warnings[0]["kind"] == "skill_not_found"

    def test_missing_from_config_detected(self, tmp_path: Path) -> None:
        """section_map = {Key Decisions} but template has Key Decisions + Insights Discovered
        → 1 warning: Insights Discovered missing from config."""
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text(_SKILL_TEMPLATE_TWO_HEADINGS)
        section_map = {"Key Decisions": "decisions"}

        warnings = check_section_map_drift(skill_path, section_map)
        kinds = [w["kind"] for w in warnings]
        values = [w["value"] for w in warnings]

        assert len(warnings) == 1
        assert "missing_from_config" in kinds
        assert "Insights Discovered" in values
        assert "'Insights Discovered' has no section_map entry" in warnings[0]["message"]

    def test_missing_from_template_detected(self, tmp_path: Path) -> None:
        """section_map = {Key Decisions, Random Section} but template only has Key Decisions
        → 1 warning: Random Section missing from template."""
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text(_SKILL_TEMPLATE_TWO_HEADINGS)
        section_map = {"Key Decisions": "decisions", "Random Section": "random"}

        warnings = check_section_map_drift(skill_path, section_map)
        kinds = [w["kind"] for w in warnings]
        values = [w["value"] for w in warnings]

        # Insights Discovered missing from config (1) + Random Section missing from template (1)
        assert any(k == "missing_from_template" for k in kinds)
        assert "Random Section" in values
        assert any(
            "section_map key 'Random Section' has no matching H2" in w["message"] for w in warnings
        )

    def test_reverse_case_missing_from_template_only(self, tmp_path: Path) -> None:
        """Pure reverse: section_map has extra key not in template."""
        skill_path = tmp_path / "SKILL.md"
        # Template with only Key Decisions
        skill_path.write_text(
            "---\n**7.** Write:\n\n   ```\n   ## Key Decisions\n   ```\n\n**8.** Done.\n"
        )
        section_map = {"Key Decisions": "decisions", "Random Section": "random"}

        warnings = check_section_map_drift(skill_path, section_map)
        missing_tmpl = [w for w in warnings if w["kind"] == "missing_from_template"]
        assert len(missing_tmpl) == 1
        assert missing_tmpl[0]["value"] == "Random Section"

    def test_no_drift_no_warnings(self, tmp_path: Path) -> None:
        """Exact match → no warnings."""
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text(_SKILL_TEMPLATE_TWO_HEADINGS)
        section_map = {
            "Key Decisions": "decisions",
            "Insights Discovered": "insights",
        }
        warnings = check_section_map_drift(skill_path, section_map)
        assert warnings == []

    def test_both_empty_no_warnings(self, tmp_path: Path) -> None:
        """Empty section_map + SKILL with no step7 → no warnings."""
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text(_SKILL_NO_STEP7)
        warnings = check_section_map_drift(skill_path, {})
        assert warnings == []

    def test_both_directions_simultaneously(self, tmp_path: Path) -> None:
        """section_map = {Key Decisions, Extra Key} + template = {Key Decisions, New H2}
        → missing_from_template: Extra Key; missing_from_config: New H2."""
        skill_path = tmp_path / "SKILL.md"
        lines = [
            "---",
            "**7.** Write:",
            "",
            "   ```",
            "   ## Key Decisions",
            "   ## New H2",
            "   ```",
            "",
            "**8.** Done.",
            "",
        ]
        skill_path.write_text("\n".join(lines))
        section_map = {"Key Decisions": "decisions", "Extra Key": "extra"}
        warnings = check_section_map_drift(skill_path, section_map)

        tmpl_warns = [w for w in warnings if w["kind"] == "missing_from_template"]
        cfg_warns = [w for w in warnings if w["kind"] == "missing_from_config"]

        assert len(tmpl_warns) == 1
        assert tmpl_warns[0]["value"] == "Extra Key"
        assert len(cfg_warns) == 1
        assert cfg_warns[0]["value"] == "New H2"
