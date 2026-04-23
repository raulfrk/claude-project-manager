"""End-to-end integration tests for wiki ↔ proj coupling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from server.lib import config as config_mod
from server.tools import scope as wiki_scope


@pytest.fixture
def integrated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a scratch ~/.claude/ layout w/ proj.yaml; redirect wiki_scope_detect paths."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "proj.yaml").write_text(yaml.safe_dump({"version": 1}))
    monkeypatch.setattr(wiki_scope, "_PROJ_YAML_PATH", claude / "proj.yaml")
    monkeypatch.setattr(wiki_scope, "_SESSION_YAML_PATH", claude / "proj-session.yaml")
    return claude


class TestWikiProjIntegration:
    def test_scope_detect_no_session(self, integrated_home: Path) -> None:
        """proj.yaml exists but no session file → global."""
        result = json.loads(wiki_scope.wiki_scope_detect())
        assert result == {"scope": "global", "proj_present": True}

    def test_scope_detect_with_active_project(self, integrated_home: Path) -> None:
        """Writing active project to session file surfaces via wiki_scope_detect."""
        (integrated_home / "proj-session.yaml").write_text(
            yaml.safe_dump({"active": "e2e-test-project"})
        )
        result = json.loads(wiki_scope.wiki_scope_detect())
        assert result["scope"] == "project:e2e-test-project"
        assert result["proj_present"] is True

    def test_scope_detect_session_without_proj(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Session file alone → detects scope but proj_present=False."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "proj-session.yaml").write_text(yaml.safe_dump({"active": "orphan"}))
        monkeypatch.setattr(wiki_scope, "_PROJ_YAML_PATH", claude / "proj.yaml")
        monkeypatch.setattr(wiki_scope, "_SESSION_YAML_PATH", claude / "proj-session.yaml")

        result = json.loads(wiki_scope.wiki_scope_detect())
        assert result["scope"] == "project:orphan"
        assert result["proj_present"] is False

    def test_wiki_config_defaults_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wiki.yaml missing → config loads defaults."""
        monkeypatch.setattr(config_mod, "_DEFAULT_CONFIG_PATH", tmp_path / "wiki.yaml")
        cfg = config_mod.load_config()
        assert cfg.enabled is False
        assert cfg.reingest_cooldown_hours == 24

    def test_full_round_trip_active_project_flows_through(self, integrated_home: Path) -> None:
        """Simulate: proj sets active project → wiki reads → scope matches."""
        # Step 1: proj writes session file (same format proj state.py writes)
        (integrated_home / "proj-session.yaml").write_text(
            yaml.safe_dump({"active": "full-round-trip"})
        )

        # Step 2: wiki reads scope
        result = json.loads(wiki_scope.wiki_scope_detect())
        assert result["scope"] == "project:full-round-trip"
        assert result["proj_present"] is True

        # Step 3: clear (simulates proj clear_session_active)
        (integrated_home / "proj-session.yaml").unlink()
        result_after_clear = json.loads(wiki_scope.wiki_scope_detect())
        assert result_after_clear == {"scope": "global", "proj_present": True}
