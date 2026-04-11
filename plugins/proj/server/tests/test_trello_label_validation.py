"""Tests for Trello label name normalization + tiebreak (todo 506)."""

from __future__ import annotations

import unicodedata

import pytest

from server.lib.trello_label_validation import (
    LabelNameError,
    TrelloLabel,
    match_label,
    normalize_label_name,
)


class TestNormalizeLabelName:
    def test_label_name_strip_whitespace(self) -> None:
        assert normalize_label_name("  proj  ") == "proj"

    def test_label_name_reject_whitespace_only(self) -> None:
        with pytest.raises(LabelNameError, match="Label name is empty"):
            normalize_label_name("   ")

    def test_label_name_reject_empty_string(self) -> None:
        with pytest.raises(LabelNameError, match="Label name is empty"):
            normalize_label_name("")

    def test_label_name_reject_control_char_newline(self) -> None:
        with pytest.raises(LabelNameError, match="control characters"):
            normalize_label_name("proj\n")

    def test_label_name_reject_control_char_tab(self) -> None:
        with pytest.raises(LabelNameError, match="control characters"):
            normalize_label_name("proj\t")

    def test_label_name_reject_control_char_cr(self) -> None:
        with pytest.raises(LabelNameError, match="control characters"):
            normalize_label_name("proj\r")

    def test_label_name_nfc_normalization(self) -> None:
        # Decomposed "café" (e + combining acute) should normalize to composed NFC.
        decomposed = "cafe\u0301"
        composed = "caf\u00e9"
        assert unicodedata.normalize("NFC", decomposed) == composed
        assert normalize_label_name(decomposed) == composed
        assert normalize_label_name(composed) == composed

    def test_label_name_case_sensitive(self) -> None:
        # "Proj" and "proj" must normalize to their distinct case.
        assert normalize_label_name("Proj") == "Proj"
        assert normalize_label_name("proj") == "proj"
        assert normalize_label_name("Proj") != normalize_label_name("proj")

    def test_label_name_length_soft_cap(self, caplog: pytest.LogCaptureFixture) -> None:
        # Name > 50 chars warns but does not raise.
        long_name = "p" * 60
        with caplog.at_level("WARNING"):
            result = normalize_label_name(long_name)
        assert result == long_name
        assert any("soft cap" in rec.message for rec in caplog.records)


class TestMatchLabel:
    def test_label_name_match_single(self) -> None:
        labels = [TrelloLabel(id="L1", name="proj", color="blue")]
        match = match_label("proj", "blue", labels)
        assert match is not None
        assert match.id == "L1"

    def test_label_name_match_none(self) -> None:
        labels = [TrelloLabel(id="L1", name="other", color="blue")]
        assert match_label("proj", "blue", labels) is None

    def test_label_name_duplicate_tiebreak_by_color(self) -> None:
        """Two labels named 'proj' with different colors → prefer preferred color."""
        labels = [
            TrelloLabel(id="L1", name="proj", color="red"),
            TrelloLabel(id="L2", name="proj", color="blue"),
        ]
        match = match_label("proj", "blue", labels)
        assert match is not None
        assert match.id == "L2"

    def test_label_name_duplicate_tiebreak_first_api_order(self) -> None:
        """Two labels named 'proj' same non-preferred color → first in API order."""
        labels = [
            TrelloLabel(id="L1", name="proj", color="red"),
            TrelloLabel(id="L2", name="proj", color="yellow"),
        ]
        match = match_label("proj", "blue", labels)
        assert match is not None
        assert match.id == "L1"

    def test_label_name_duplicate_exact_color_ambiguous_raises(self) -> None:
        """Two labels named 'proj' with the same preferred color → hard error."""
        labels = [
            TrelloLabel(id="L1", name="proj", color="blue"),
            TrelloLabel(id="L2", name="proj", color="blue"),
        ]
        with pytest.raises(LabelNameError, match="Multiple labels named 'proj'"):
            match_label("proj", "blue", labels)

    def test_label_name_trello_trims_whitespace_on_write(self) -> None:
        """Trello silently trims whitespace; comparison must handle the mismatch."""
        # User configured "  proj  " (stripped at normalize time to "proj").
        # Trello stores "proj". The match should find it.
        configured = normalize_label_name("  proj  ")
        board_labels = [TrelloLabel(id="L1", name="proj", color="blue")]
        match = match_label(configured, "blue", board_labels)
        assert match is not None
        assert match.id == "L1"

    def test_label_name_case_sensitive_comparison(self) -> None:
        """'Proj' on board must NOT match 'proj' configured."""
        labels = [TrelloLabel(id="L1", name="Proj", color="blue")]
        assert match_label("proj", "blue", labels) is None


class TestTrelloSyncSkillDelegation:
    """r2 regression: trello-sync SKILL.md must delegate label creation to trello-setup."""

    def test_trello_sync_skill_no_create_label_substring(self) -> None:
        from pathlib import Path

        # tests/ → server/ → proj/ → plugins/ → repo root
        repo_root = Path(__file__).resolve().parents[4]
        skill = repo_root / "plugins" / "proj" / "skills" / "trello-sync" / "SKILL.md"
        text = skill.read_text()
        assert "create_label" not in text, (
            "trello-sync/SKILL.md must not reference create_label — delegate to trello-setup"
        )
        assert "Label name is empty" not in text, (
            "trello-sync/SKILL.md must not duplicate non-empty label validation — "
            "delegate to trello-setup"
        )
