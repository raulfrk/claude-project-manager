from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project dir with .schema-version=1 (legacy) + YAML data."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".schema-version").write_text("1\n")
    (root / "todos.yaml").write_text(yaml.safe_dump([]))
    (root / "archive.yaml").write_text(yaml.safe_dump([]))
    return root
