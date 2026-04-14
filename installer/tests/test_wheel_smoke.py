"""Wheel build smoke tests — verify package data is included in the built wheel.

Gap covered: bug 592 shipped marketplace.json missing from the wheel because
pyproject.toml force-include was not configured.  These tests catch that class
of regression by building the wheel and inspecting its contents.

Motivation: the e2e test suite mocks plugin_cli and never builds a real wheel,
so missing package data went undetected.
"""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

# Root of the project (where pyproject.toml lives)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def built_wheel(tmp_path: Path) -> Path:
    """Build a wheel into tmp_path and return the .whl file path."""
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"uv build --wheel failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"Expected 1 wheel, found {len(wheels)}: {wheels}"
    return wheels[0]


class TestWheelContents:
    """Verify the built wheel contains required package data files."""

    def test_wheel_builds_successfully(self, built_wheel: Path) -> None:
        """Wheel build completes and produces a valid zip."""
        assert built_wheel.exists()
        assert zipfile.is_zipfile(built_wheel)

    def test_marketplace_json_in_wheel(self, built_wheel: Path) -> None:
        """marketplace.json must be included in the wheel (bug 592 regression)."""
        with zipfile.ZipFile(built_wheel) as zf:
            names = zf.namelist()
            matches = [n for n in names if n.endswith("marketplace.json")]
            assert matches, (
                "marketplace.json not found in wheel. Contents:\n"
                + "\n".join(sorted(names))
            )

    def test_defaults_yaml_in_wheel(self, built_wheel: Path) -> None:
        """defaults.yaml must be included in the wheel."""
        with zipfile.ZipFile(built_wheel) as zf:
            names = zf.namelist()
            matches = [n for n in names if n.endswith("defaults.yaml")]
            assert matches, "defaults.yaml not found in wheel. Contents:\n" + "\n".join(
                sorted(names)
            )

    def test_marketplace_json_is_valid(self, built_wheel: Path) -> None:
        """marketplace.json inside the wheel must be valid JSON with plugin entries."""
        with zipfile.ZipFile(built_wheel) as zf:
            matches = [n for n in zf.namelist() if n.endswith("marketplace.json")]
            assert matches, "marketplace.json not found in wheel"
            data = json.loads(zf.read(matches[0]))
            assert "plugins" in data, "marketplace.json missing 'plugins' key"
            plugins = data["plugins"]
            assert len(plugins) > 0, "marketplace.json has no plugins"
            # Verify expected plugin names are present
            names = {p["name"] for p in plugins}
            for expected in ("proj", "router", "sandbox"):
                assert expected in names, (
                    f"Expected plugin '{expected}' in marketplace.json"
                )
