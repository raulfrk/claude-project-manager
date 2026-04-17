from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Minimal project dir with proj.yaml (schema_version=1)."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "proj.yaml").write_text(yaml.safe_dump({"name": "demo"}))
    (root / "todos.yaml").write_text(yaml.safe_dump([]))
    (root / "archive.yaml").write_text(yaml.safe_dump([]))
    return root
