"""Tests for proj_explore_codebase MCP tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.tools.explore import explore_codebase


def _make_tree(root: Path, files: dict[str, str]) -> None:
    """Create a directory tree from a dict of relative-path → content."""
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


class TestExploreCodbase:
    def test_nonexistent_path_returns_error(self, tmp_path: Path) -> None:
        result = explore_codebase(str(tmp_path / "nonexistent"))
        assert "error" in result

    def test_empty_dir_returns_empty_collections(self, tmp_path: Path) -> None:
        result = explore_codebase(str(tmp_path))
        assert result["tech_stack"] == []
        assert result["entry_points"] == []
        assert result["key_dirs"] == []
        assert result["file_tree"] == []

    def test_detects_python_tech_stack(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'")
        result = explore_codebase(str(tmp_path))
        assert "Python" in result["tech_stack"]
        assert "pyproject.toml" in result["config_files"]

    def test_detects_node_tech_stack(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "x"}')
        result = explore_codebase(str(tmp_path))
        assert "Node/JavaScript" in result["tech_stack"]

    def test_detects_multiple_stacks(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "package.json").write_text("{}")
        result = explore_codebase(str(tmp_path))
        assert "Python" in result["tech_stack"]
        assert "Node/JavaScript" in result["tech_stack"]

    def test_detects_entry_points(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("# main")
        (tmp_path / "app.py").write_text("# app")
        result = explore_codebase(str(tmp_path))
        assert "main.py" in result["entry_points"]
        assert "app.py" in result["entry_points"]

    def test_entry_points_in_subdirs(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {"src/main.py": "# main", "cli.py": "# cli"})
        result = explore_codebase(str(tmp_path))
        assert any("main.py" in ep for ep in result["entry_points"])
        assert any("cli.py" in ep for ep in result["entry_points"])

    def test_key_dirs_are_top_level_subdirs(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "docs").mkdir()
        result = explore_codebase(str(tmp_path))
        assert "src" in result["key_dirs"]
        assert "tests" in result["key_dirs"]
        assert "docs" in result["key_dirs"]

    def test_ignored_dirs_excluded(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "src").mkdir()
        result = explore_codebase(str(tmp_path))
        assert ".git" not in result["key_dirs"]
        assert "node_modules" not in result["key_dirs"]
        assert "__pycache__" not in result["key_dirs"]
        assert "src" in result["key_dirs"]

    def test_file_types_counted(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {
            "a.py": "", "b.py": "", "c.ts": "", "README.md": "",
        })
        result = explore_codebase(str(tmp_path))
        assert result["file_types"]["py"] == 2
        assert result["file_types"]["ts"] == 1
        assert result["file_types"]["md"] == 1

    def test_file_tree_capped_at_max_files(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        for i in range(50):
            (tmp_path / "src" / f"file{i}.py").write_text("")
        result = explore_codebase(str(tmp_path), max_files=20)
        assert len(result["file_tree"]) == 20

    def test_arch_note_is_non_empty_string(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        result = explore_codebase(str(tmp_path))
        assert isinstance(result["arch_note"], str)
        assert len(result["arch_note"]) > 0

    def test_arch_note_mentions_tech_stack(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"')
        result = explore_codebase(str(tmp_path))
        assert "Rust" in result["arch_note"]

    def test_returns_dict_with_all_keys(self, tmp_path: Path) -> None:
        result = explore_codebase(str(tmp_path))
        assert "tech_stack" in result
        assert "entry_points" in result
        assert "key_dirs" in result
        assert "config_files" in result
        assert "file_types" in result
        assert "file_tree" in result
        assert "arch_note" in result

    def test_tilde_path_expanded(self) -> None:
        # Should not error — just return whatever is in home dir
        result = explore_codebase("~", max_files=5)
        # home dir always exists
        assert "error" not in result

    def test_readme_detected_in_arch_note(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# My Project")
        result = explore_codebase(str(tmp_path))
        assert "README.md" in result["arch_note"]
