"""Snapshot tests for postmortem additions to managed_section.md.

Verifies:
1. The Append-only log convention `op` set includes `postmortem`.
2. The new `Postmortem ritual` bullet is present.
3. The rule body mentions the required substantive keywords.
"""

from __future__ import annotations

from pathlib import Path

MANAGED = Path(__file__).resolve().parents[1] / "claudemd" / "managed_section.md"


def test_op_set_includes_postmortem() -> None:
    text = MANAGED.read_text()
    # The op enumeration line is part of "Append-only log convention" rule
    assert "Append-only log convention" in text
    # Substring covering the enum closing
    assert ", postmortem}" in text


def test_postmortem_ritual_rule_present() -> None:
    text = MANAGED.read_text()
    assert "**Postmortem ritual**" in text
    assert "5-line postmortem" in text


def test_postmortem_rule_keywords_present() -> None:
    """Required substantive keywords in the rule body."""
    text = MANAGED.read_text()
    # Find the postmortem rule line + lookahead window
    idx = text.find("**Postmortem ritual**")
    assert idx >= 0
    rule_body = text[idx : idx + 2500]
    required = [
        "5-line",
        "mast:",
        "microsoft:",
        "boundary-drift",
        "todo 820",
        "sync.wiki.capture_notes_as_log",
        "Reproduce before fix",
    ]
    for kw in required:
        assert kw in rule_body, f"missing required keyword: {kw}"
