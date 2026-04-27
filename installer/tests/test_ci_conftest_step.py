"""Snapshot test — .github/workflows/ci.yml has the conftest install + run steps."""

from __future__ import annotations

from pathlib import Path

CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def test_ci_yml_has_conftest_install():
    """Conftest install step references the canonical release URL."""
    text = CI_YML.read_text()
    assert "Install conftest" in text
    assert "github.com/open-policy-agent/conftest/releases" in text


def test_ci_yml_has_rego_policies_step():
    """Rego policies run step exercises all 4 invariants + verify."""
    text = CI_YML.read_text()
    assert "Run cpm Rego policies" in text
    for invariant in [
        "shared_version_cascade",
        "version_parity",
        "port_uniqueness",
        "condition_paths",
        "Rego unit tests",
    ]:
        assert invariant in text, f"missing: {invariant!r}"
