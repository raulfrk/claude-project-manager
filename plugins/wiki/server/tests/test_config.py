"""Tests for lib/config.py."""

from pathlib import Path

import pytest
import yaml

from server.lib.config import config_exists, config_path, load_config, save_config
from server.lib.models import WikiConfig


class TestLoadConfig:
    def test_load_default_when_missing(self, wiki_cfg_path: Path) -> None:
        cfg = load_config()
        assert cfg == WikiConfig()

    def test_load_existing(self, wiki_cfg_path: Path) -> None:
        wiki_cfg_path.write_text(
            yaml.safe_dump(
                {
                    "enabled": True,
                    "wiki_dir": str(wiki_cfg_path.parent / "wiki"),
                    "reingest_cooldown_hours": 48,
                }
            )
        )
        cfg = load_config()
        assert cfg.enabled is True
        assert cfg.reingest_cooldown_hours == 48

    def test_load_malformed_yaml_returns_defaults(self, wiki_cfg_path: Path) -> None:
        wiki_cfg_path.write_text("enabled: : :")  # invalid YAML
        cfg = load_config()
        assert cfg == WikiConfig()

    def test_config_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Only when fixture isn't in play: config_path() → ~/.claude/wiki.yaml
        from server.lib import config as cfg_mod

        monkeypatch.setattr(cfg_mod, "_DEFAULT_CONFIG_PATH", Path.home() / ".claude" / "wiki.yaml")
        assert config_path() == Path.home() / ".claude" / "wiki.yaml"


class TestSaveConfig:
    def test_save_roundtrip(self, wiki_cfg_path: Path) -> None:
        cfg = WikiConfig(
            enabled=True,
            wiki_dir=wiki_cfg_path.parent / "w",
            reingest_cooldown_hours=6,
            bootstrap_pending=True,
            session_ingest_section_map={"K": "v"},
        )
        save_config(cfg)
        assert wiki_cfg_path.exists()
        reloaded = load_config()
        assert reloaded == cfg

    def test_save_creates_parent_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        deep = tmp_path / "a" / "b" / "wiki.yaml"
        monkeypatch.setattr("server.lib.config._DEFAULT_CONFIG_PATH", deep)
        save_config(WikiConfig(enabled=True))
        assert deep.exists()


class TestConfigExists:
    def test_false_when_missing(self, wiki_cfg_path: Path) -> None:
        assert config_exists() is False

    def test_true_when_present(self, wiki_cfg_path: Path) -> None:
        wiki_cfg_path.write_text("enabled: true\n")
        assert config_exists() is True
