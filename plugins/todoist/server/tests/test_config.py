"""Tests for TodoistConfig loading: YAML file, defaults, error cases, caching."""

from __future__ import annotations

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


class TestValidConfig:
    def test_loads_all_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text(
            "api_token: tok-123\nenabled: false\nauto_sync: false\nroot_only: true\n"
        )
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        cfg = load_config()
        assert cfg.api_token == "tok-123"
        assert cfg.enabled is False
        assert cfg.auto_sync is False
        assert cfg.root_only is True

    def test_defaults_with_only_api_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text("api_token: tok-456\n")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        cfg = load_config()
        assert cfg.api_token == "tok-456"
        assert cfg.enabled is True
        assert cfg.auto_sync is True
        assert cfg.root_only is False

    def test_extra_fields_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text("api_token: tok-789\nfoo: bar\nextra: 42\n")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        cfg = load_config()
        assert cfg.api_token == "tok-789"
        assert not hasattr(cfg, "foo")


class TestMissingFile:
    def test_missing_file_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TODOIST_CONFIG", str(tmp_path / "nonexistent.yaml"))

        with pytest.raises(ValueError, match="Todoist not configured"):
            load_config()


class TestMalformedYaml:
    def test_malformed_yaml_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text(":\n  - :\n    bad: [")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config()

    def test_empty_file_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text("")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config()

    def test_scalar_yaml_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text("just a string\n")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config()


class TestMissingApiToken:
    def test_missing_api_token_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text("enabled: true\n")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        with pytest.raises(ValueError, match="missing api_token"):
            load_config()

    def test_empty_api_token_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text("api_token: '  '\n")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        with pytest.raises(ValueError, match="missing api_token"):
            load_config()


class TestEnvVarOverride:
    def test_env_var_overrides_default_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "custom-todoist.yaml"
        cfg_file.write_text("api_token: custom-tok\n")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        cfg = load_config()
        assert cfg.api_token == "custom-tok"


class TestCaching:
    def test_second_call_returns_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "todoist.yaml"
        cfg_file.write_text("api_token: tok\n")
        monkeypatch.setenv("TODOIST_CONFIG", str(cfg_file))

        c1 = load_config()
        c2 = load_config()
        assert c1 is c2
