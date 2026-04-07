"""Unit tests for scripts/update_readme.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import update_readme as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MARKETPLACE = {
    "plugins": [
        {
            "name": "proj",
            "version": "0.36.0",
            "category": "project-management",
            "description": "Full project lifecycle management",
        },
        {
            "name": "sandbox",
            "version": "0.2.0",
            "category": "security",
            "description": "Sandbox settings management",
        },
    ]
}


def _write_marketplace(path: Path, data: dict | None = None) -> None:
    mp_dir = path / ".claude-plugin"
    mp_dir.mkdir(parents=True, exist_ok=True)
    (mp_dir / "marketplace.json").write_text(json.dumps(data or SAMPLE_MARKETPLACE))


def _write_readme(path: Path, content: str | None = None) -> None:
    if content is None:
        content = (
            "# README\n"
            "<!-- AUTO:badges-start -->\n"
            "old badges\n"
            "<!-- AUTO:badges-end -->\n"
            "\n"
            "<!-- AUTO:plugins-table-start -->\n"
            "old table\n"
            "<!-- AUTO:plugins-table-end -->\n"
        )
    (path / "README.md").write_text(content)


def _write_test_summary(path: Path, total_passing: int = 42) -> None:
    scripts_dir = path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / ".test-summary.json").write_text(
        json.dumps({"total_passing": total_passing})
    )


def _run_main(tmp_path: Path) -> int:
    """Run main() with patched REPO_ROOT paths."""
    with (
        mock.patch.object(mod, "REPO_ROOT", tmp_path),
        mock.patch.object(mod, "README_PATH", tmp_path / "README.md"),
        mock.patch.object(
            mod, "MARKETPLACE_PATH", tmp_path / ".claude-plugin" / "marketplace.json"
        ),
        mock.patch.object(
            mod, "TEST_SUMMARY_PATH", tmp_path / "scripts" / ".test-summary.json"
        ),
    ):
        return mod.main()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseMarketplace:
    def test_parse_marketplace(self, tmp_path: Path) -> None:
        _write_marketplace(tmp_path)
        mp_path = tmp_path / ".claude-plugin" / "marketplace.json"
        with mock.patch.object(mod, "MARKETPLACE_PATH", mp_path):
            data = mod.load_marketplace()
        assert data["plugins"][0]["name"] == "proj"
        assert len(data["plugins"]) == 2


class TestGeneratePluginsTable:
    def test_generate_plugins_table(self) -> None:
        table = mod.generate_plugins_table(SAMPLE_MARKETPLACE["plugins"])
        assert "| **proj**" in table
        assert "| **sandbox**" in table
        assert "0.36.0" in table
        assert "project-management" in table
        lines = table.strip().splitlines()
        # header + separator + 2 data rows
        assert len(lines) == 4

    def test_empty_plugins(self) -> None:
        table = mod.generate_plugins_table([])
        assert "No plugins found" in table
        # Should still have header row
        assert "| Plugin |" in table


class TestGenerateBadges:
    def test_generate_badges(self) -> None:
        badges = mod.generate_badges("1.2.3", 42)
        assert "version-1.2.3-blue" in badges
        assert "tests-42%20passing" in badges
        assert "license-MIT" in badges

    def test_generate_badges_no_tests(self) -> None:
        badges = mod.generate_badges("1.0.0", None)
        assert "tests-" not in badges
        assert "version-1.0.0" in badges
        assert "license-MIT" in badges


class TestReplaceMarkers:
    def test_replace_markers_plugins(self) -> None:
        content = (
            "before\n"
            "<!-- AUTO:plugins-table-start -->\n"
            "old content\n"
            "<!-- AUTO:plugins-table-end -->\n"
            "after"
        )
        result = mod.replace_markers(content, {"plugins-table": "new content"})
        assert "new content" in result
        assert "old content" not in result
        assert "before" in result
        assert "after" in result

    def test_replace_markers_badges(self) -> None:
        content = "<!-- AUTO:badges-start -->\nold badges\n<!-- AUTO:badges-end -->\n"
        result = mod.replace_markers(content, {"badges": "new badges"})
        assert "new badges" in result
        assert "old badges" not in result

    def test_missing_markers(self, capsys: pytest.CaptureFixture[str]) -> None:
        content = "no markers here"
        result = mod.replace_markers(content, {"plugins-table": "stuff"})
        assert result == content
        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_missing_end_marker(self, capsys: pytest.CaptureFixture[str]) -> None:
        content = "<!-- AUTO:badges-start -->\nsome text\nno end"
        result = mod.replace_markers(content, {"badges": "new"})
        # Pattern won't match without end marker, so content unchanged
        assert result == content
        captured = capsys.readouterr()
        assert "WARNING" in captured.err


class TestIdempotent:
    def test_idempotent(self, tmp_path: Path) -> None:
        _write_marketplace(tmp_path)
        _write_readme(tmp_path)
        _write_test_summary(tmp_path)

        # First run modifies
        rc1 = _run_main(tmp_path)
        content_after_first = (tmp_path / "README.md").read_text()

        # Second run should be unchanged
        rc2 = _run_main(tmp_path)
        content_after_second = (tmp_path / "README.md").read_text()

        assert rc1 == 1  # modified
        assert rc2 == 0  # unchanged
        assert content_after_first == content_after_second


class TestMissingFiles:
    def test_missing_test_summary(self, tmp_path: Path) -> None:
        _write_marketplace(tmp_path)
        _write_readme(tmp_path)
        # No test summary file -- should not crash
        rc = _run_main(tmp_path)
        # Should still produce output (modified from placeholder)
        assert rc in (0, 1)
        content = (tmp_path / "README.md").read_text()
        assert "tests-" not in content  # no test badge

    def test_missing_marketplace(self, tmp_path: Path) -> None:
        _write_readme(tmp_path)
        rc = _run_main(tmp_path)
        assert rc == 1

    def test_missing_readme(self, tmp_path: Path) -> None:
        _write_marketplace(tmp_path)
        rc = _run_main(tmp_path)
        assert rc == 1


class TestExitCodes:
    def test_exit_code_modified(self, tmp_path: Path) -> None:
        _write_marketplace(tmp_path)
        _write_readme(tmp_path)
        _write_test_summary(tmp_path)
        rc = _run_main(tmp_path)
        assert rc == 1

    def test_exit_code_unchanged(self, tmp_path: Path) -> None:
        _write_marketplace(tmp_path)
        _write_readme(tmp_path)
        _write_test_summary(tmp_path)
        # First run to update
        _run_main(tmp_path)
        # Second run should be unchanged
        rc = _run_main(tmp_path)
        assert rc == 0


class TestEdgeCases:
    def test_pipe_in_description(self) -> None:
        plugins = [
            {
                "name": "test",
                "version": "1.0.0",
                "category": "utils",
                "description": "Does this | that",
            }
        ]
        table = mod.generate_plugins_table(plugins)
        assert "Does this \\| that" in table
        # The escaped pipe should appear in the row, not a raw unescaped one
        lines = table.splitlines()
        data_line = lines[2]
        assert "Does this \\| that" in data_line

    def test_missing_category(self) -> None:
        plugins = [
            {
                "name": "nocategory",
                "version": "1.0.0",
                "description": "No category field",
            }
        ]
        table = mod.generate_plugins_table(plugins)
        assert "uncategorized" in table
