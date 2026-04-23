"""Shared pytest fixtures for wiki plugin."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def wiki_cfg_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a temp config path + redirect ~/.claude/wiki.yaml to it.

    Tests that load config will see the temp file instead of the user's real one.
    """
    cfg_path = tmp_path / "wiki.yaml"
    monkeypatch.setattr("server.lib.config._DEFAULT_CONFIG_PATH", cfg_path)
    return cfg_path


@pytest.fixture
def wiki_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a temp ~/.claude/wiki/ root + redirect config's wiki_dir there."""
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "pages").mkdir()
    return root
