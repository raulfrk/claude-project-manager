"""Tests for configure_wiki + _write_wiki_integration_result (Phase 4b)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from rich.console import Console

from installer.flow.integration_config import (
    _write_wiki_integration_result,
    configure_wiki,
)


class TestConfigureWiki:
    def test_cancel_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Canceling form returns None."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        with patch("installer.flow.integration_config.run_form", return_value=None):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_wiki(console)

        assert result is None

    def test_fields_without_proj(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When proj NOT selected: 4 fields (enabled, profile, custom_categories, bootstrap_pending)."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        fields_captured: list = []

        def fake_run_form(fields, console, **kwargs):
            fields_captured.extend(fields)
            return None  # Cancel

        with patch(
            "installer.flow.integration_config.run_form", side_effect=fake_run_form
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            configure_wiki(console, proj_selected=False)

        keys = [f.key for f in fields_captured]
        assert keys == [
            "enabled",
            "profile",
            "custom_categories",
            "bootstrap_pending",
        ]

    def test_fields_with_proj(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When proj selected: 6 fields (adds proj_auto_ingest_sessions + proj_capture_notes_as_log)."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        fields_captured: list = []

        def fake_run_form(fields, console, **kwargs):
            fields_captured.extend(fields)
            return None

        with patch(
            "installer.flow.integration_config.run_form", side_effect=fake_run_form
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            configure_wiki(console, proj_selected=True)

        keys = [f.key for f in fields_captured]
        assert "proj_auto_ingest_sessions" in keys
        assert "proj_capture_notes_as_log" in keys
        assert len(keys) == 6

    def test_defaults_loaded_from_existing_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Existing wiki.yaml + config.yaml values appear as defaults."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "wiki.yaml").write_text(
            yaml.safe_dump({"enabled": True, "bootstrap_pending": True})
        )
        (fake_home / ".claude" / "wiki").mkdir()
        (fake_home / ".claude" / "wiki" / "config.yaml").write_text(
            yaml.safe_dump({"profile": "personal"})
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        fields_captured: list = []

        def fake_run_form(fields, console, **kwargs):
            fields_captured.extend(fields)
            return None

        with patch(
            "installer.flow.integration_config.run_form", side_effect=fake_run_form
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            configure_wiki(console, proj_selected=False)

        field_by_key = {f.key: f for f in fields_captured}
        assert field_by_key["enabled"].default is True
        assert field_by_key["profile"].default == "personal"
        assert field_by_key["bootstrap_pending"].default is True

    def test_submit_returns_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Submitting form returns result dict."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        expected = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        with patch("installer.flow.integration_config.run_form", return_value=expected):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_wiki(console, proj_selected=False)

        assert result == expected


class TestWriteWikiIntegrationResult:
    def test_writes_wiki_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wiki.yaml is written w/ enabled, wiki_dir, reingest_cooldown, bootstrap_pending, session_ingest."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        wiki_yaml = fake_home / ".claude" / "wiki.yaml"
        assert wiki_yaml.exists()
        data = yaml.safe_load(wiki_yaml.read_text())
        assert data["enabled"] is True
        assert data["wiki_dir"] == str(fake_home / ".claude" / "wiki")
        assert data["reingest_cooldown_hours"] == 24
        assert data["bootstrap_pending"] is False
        assert data["session_ingest"] == {"section_map": {}}

    def test_writes_config_yaml_software_profile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """software profile config.yaml has required_frontmatter and lint settings."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        cfg = fake_home / ".claude" / "wiki" / "config.yaml"
        data = yaml.safe_load(cfg.read_text())
        assert data["schema_version"] == 1
        assert data["profile"] == "software"
        assert "categories" not in data
        assert "title" in data["required_frontmatter"]
        assert data["lint"]["stale_after_days"] == 90

    def test_custom_profile_writes_categories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """custom profile parses custom_categories into config.yaml categories."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "custom",
            "custom_categories": "foo, bar, baz",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        cfg = fake_home / ".claude" / "wiki" / "config.yaml"
        data = yaml.safe_load(cfg.read_text())
        assert data["profile"] == "custom"
        assert data["categories"] == ["foo", "bar", "baz"]

    def test_custom_profile_empty_categories_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """custom profile w/ empty categories falls back to ['notes']."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "custom",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        cfg = fake_home / ".claude" / "wiki" / "config.yaml"
        data = yaml.safe_load(cfg.read_text())
        assert data["categories"] == ["notes"]

    def test_creates_category_subdirs_software(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """software profile creates concepts/decisions/references/pitfalls/entities subdirs."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        pages = fake_home / ".claude" / "wiki" / "pages"
        assert (pages / "concepts").is_dir()
        assert (pages / "decisions").is_dir()
        assert (pages / "references").is_dir()
        assert (pages / "pitfalls").is_dir()
        assert (pages / "entities").is_dir()

    def test_creates_category_subdirs_personal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """personal profile creates journal/topics/people/places/lessons subdirs."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "personal",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        pages = fake_home / ".claude" / "wiki" / "pages"
        assert (pages / "journal").is_dir()
        assert (pages / "topics").is_dir()
        assert (pages / "people").is_dir()
        assert (pages / "places").is_dir()
        assert (pages / "lessons").is_dir()

    def test_creates_category_subdirs_research(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """research profile creates concepts/sources/findings/questions subdirs."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "research",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        pages = fake_home / ".claude" / "wiki" / "pages"
        assert (pages / "concepts").is_dir()
        assert (pages / "sources").is_dir()
        assert (pages / "findings").is_dir()
        assert (pages / "questions").is_dir()

    def test_minimal_profile_no_subdirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """minimal profile creates pages/ but no subdirs."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "minimal",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        pages = fake_home / ".claude" / "wiki" / "pages"
        assert pages.is_dir()
        assert list(pages.iterdir()) == []

    def test_creates_category_subdirs_custom(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """custom profile creates subdirs from custom_categories."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "custom",
            "custom_categories": "foo, bar, baz",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        pages = fake_home / ".claude" / "wiki" / "pages"
        assert (pages / "foo").is_dir()
        assert (pages / "bar").is_dir()
        assert (pages / "baz").is_dir()

    def test_writes_proj_sync_wiki_when_proj_selected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When proj_selected=True, sync.wiki.* config written to proj.yaml."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
            "proj_auto_ingest_sessions": True,
            "proj_capture_notes_as_log": True,
        }
        _write_wiki_integration_result(result, proj_selected=True)

        proj_yaml = fake_home / ".claude" / "proj.yaml"
        assert proj_yaml.exists()
        data = yaml.safe_load(proj_yaml.read_text())
        sync_wiki = data["sync"]["wiki"]
        assert sync_wiki["enabled"] is True
        assert sync_wiki["auto_sync"] is True
        assert sync_wiki["auto_ingest_sessions"] is True
        assert sync_wiki["capture_notes_as_log"] is True

    def test_skips_proj_yaml_when_proj_not_selected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When proj_selected=False, proj.yaml is not modified."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        assert not (fake_home / ".claude" / "proj.yaml").exists()

    def test_preserves_existing_wiki_yaml_keys(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-wizard keys in wiki.yaml (e.g. custom reingest_cooldown_hours) survive."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "wiki.yaml").write_text(
            yaml.safe_dump(
                {
                    "enabled": False,
                    "reingest_cooldown_hours": 72,
                    "session_ingest": {"section_map": {"Key Decisions": "decisions"}},
                }
            )
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
        }
        _write_wiki_integration_result(result, proj_selected=False)

        data = yaml.safe_load((fake_home / ".claude" / "wiki.yaml").read_text())
        assert data["reingest_cooldown_hours"] == 72  # preserved
        assert data["session_ingest"]["section_map"] == {"Key Decisions": "decisions"}
        assert data["enabled"] is True  # updated by wizard

    def test_proj_yaml_merge_preserves_other_sync_integrations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Existing proj.yaml w/ other sync integrations preserved during wiki write."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump(
                {
                    "sync": {
                        "todoist": {"enabled": True, "auto_sync": True},
                    }
                }
            )
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = {
            "enabled": True,
            "profile": "software",
            "custom_categories": "",
            "bootstrap_pending": False,
            "proj_auto_ingest_sessions": False,
            "proj_capture_notes_as_log": False,
        }
        _write_wiki_integration_result(result, proj_selected=True)

        data = yaml.safe_load((fake_home / ".claude" / "proj.yaml").read_text())
        assert data["sync"]["todoist"]["enabled"] is True
        assert data["sync"]["wiki"]["enabled"] is True
