"""Smoke tests for the claudemd subpackage shipped in claude-hook-transport."""


def test_claudemd_subpackage_loads():
    from claudemd import MANAGED_SECTION, MARKER_END, MARKER_START

    assert MANAGED_SECTION.startswith(MARKER_START)
    assert MANAGED_SECTION.endswith(MARKER_END)
