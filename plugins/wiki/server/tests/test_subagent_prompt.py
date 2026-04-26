"""Test that subagent prompt template contains the EXCLUSION RULES block."""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "skills" / "ingest" / "references" / "subagent-prompt.md"
)


def test_prompt_file_exists() -> None:
    assert PROMPT_PATH.is_file(), f"Prompt file missing: {PROMPT_PATH}"


def test_exclusion_rules_block_present() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "EXCLUSION RULES" in content
    assert 'Todo IDs or any "todo NNN" references.' in content
    assert "In-flight/active/shipped/ready/blocked status framing." in content
    assert "## Todos Worked On" in content
    assert "Concepts, patterns, designs (architectural reuse value)." in content
    assert "Decisions with rejected alternatives + trade-offs." in content
    assert "Pitfalls + technical insights (gotchas, surprising behavior)." in content
    assert "EVIDENCE" in content


def test_exclusion_block_precedes_protocol_step_1() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    excl_idx = content.find("EXCLUSION RULES")
    step1_idx = content.find("1. Resolve + read source")
    assert excl_idx != -1
    assert step1_idx != -1
    assert excl_idx < step1_idx
