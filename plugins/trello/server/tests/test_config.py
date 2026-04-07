"""Tests for TrelloConfig loading: YAML file, env vars, error cases."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import server.lib.config as config_mod
from server.lib.config import load_config


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    """Reset the cached config before each test."""
    config_mod._cached_config = None
    yield  # type: ignore[misc]
    config_mod._cached_config = None


class TestLoadConfigFromYaml:
    def test_loads_from_yaml_file(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "trello.yaml"
        cfg_file.write_text("api_key: yaml-key\ntoken: yaml-token\ndefault_board_id: board123\n")
        os.environ["TRELLO_CONFIG"] = str(cfg_file)
        try:
            cfg = load_config()
            assert cfg.api_key == "yaml-key"
            assert cfg.token == "yaml-token"
            assert cfg.default_board_id == "board123"
            assert cfg.rate_limit_per_10s == 100
        finally:
            del os.environ["TRELLO_CONFIG"]

    def test_loads_custom_rate_limit(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "trello.yaml"
        cfg_file.write_text("api_key: k\ntoken: t\nrate_limit_per_10s: 50\n")
        os.environ["TRELLO_CONFIG"] = str(cfg_file)
        try:
            cfg = load_config()
            assert cfg.rate_limit_per_10s == 50
        finally:
            del os.environ["TRELLO_CONFIG"]

    def test_yaml_missing_api_key_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "trello.yaml"
        cfg_file.write_text("token: t\n")
        os.environ["TRELLO_CONFIG"] = str(cfg_file)
        try:
            with pytest.raises(ValueError, match="missing api_key or token"):
                load_config()
        finally:
            del os.environ["TRELLO_CONFIG"]

    def test_yaml_missing_token_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "trello.yaml"
        cfg_file.write_text("api_key: k\n")
        os.environ["TRELLO_CONFIG"] = str(cfg_file)
        try:
            with pytest.raises(ValueError, match="missing api_key or token"):
                load_config()
        finally:
            del os.environ["TRELLO_CONFIG"]

    def test_yaml_empty_file_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "trello.yaml"
        cfg_file.write_text("")
        os.environ["TRELLO_CONFIG"] = str(cfg_file)
        try:
            with pytest.raises(ValueError, match="missing api_key or token"):
                load_config()
        finally:
            del os.environ["TRELLO_CONFIG"]


class TestLoadConfigFromEnvVars:
    def test_loads_from_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point TRELLO_CONFIG to a non-existent file so YAML path is skipped
        monkeypatch.setenv("TRELLO_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.setenv("TRELLO_API_KEY", "env-key")
        monkeypatch.setenv("TRELLO_TOKEN", "env-token")

        cfg = load_config()
        assert cfg.api_key == "env-key"
        assert cfg.token == "env-token"
        assert cfg.default_board_id == ""

    def test_env_vars_missing_key_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRELLO_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.setenv("TRELLO_TOKEN", "env-token")
        monkeypatch.delenv("TRELLO_API_KEY", raising=False)

        with pytest.raises(ValueError, match="Trello config not found"):
            load_config()


class TestLoadConfigError:
    def test_no_config_raises_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRELLO_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.delenv("TRELLO_API_KEY", raising=False)
        monkeypatch.delenv("TRELLO_TOKEN", raising=False)

        with pytest.raises(ValueError, match="Trello config not found"):
            load_config()


class TestConfigCaching:
    def test_second_call_returns_cached(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "trello.yaml"
        cfg_file.write_text("api_key: k\ntoken: t\n")
        os.environ["TRELLO_CONFIG"] = str(cfg_file)
        try:
            c1 = load_config()
            c2 = load_config()
            assert c1 is c2
        finally:
            del os.environ["TRELLO_CONFIG"]
