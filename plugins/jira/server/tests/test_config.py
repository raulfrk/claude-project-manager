"""Tests for Jira configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import server.lib.config as config_mod
from server.lib.config import load_config


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    """Ensure each test starts with a clean config cache."""
    config_mod._cached_config = None
    yield
    config_mod._cached_config = None


class TestYamlLoading:
    def test_loads_full_yaml_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = tmp_path / "jira.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "personal_access_token": "my_pat",
                    "base_url": "https://jira.example.com",
                    "allowed_project_keys": ["PROJ", "DEV"],
                    "default_user": "alice",
                    "rate_limit_per_10s": 50,
                }
            )
        )
        monkeypatch.setenv("JIRA_CONFIG", str(config_file))

        cfg = load_config()

        assert cfg.personal_access_token == "my_pat"
        assert cfg.base_url == "https://jira.example.com"
        assert cfg.allowed_project_keys == ["PROJ", "DEV"]
        assert cfg.default_user == "alice"
        assert cfg.rate_limit_per_10s == 50

    def test_missing_pat_in_yaml_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "jira.yaml"
        config_file.write_text(yaml.dump({"base_url": "https://jira.example.com"}))
        monkeypatch.setenv("JIRA_CONFIG", str(config_file))

        with pytest.raises(ValueError, match="missing personal_access_token or base_url"):
            load_config()

    def test_missing_base_url_in_yaml_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "jira.yaml"
        config_file.write_text(yaml.dump({"personal_access_token": "pat"}))
        monkeypatch.setenv("JIRA_CONFIG", str(config_file))

        with pytest.raises(ValueError, match="missing personal_access_token or base_url"):
            load_config()


class TestEnvVarFallback:
    def test_loads_from_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point JIRA_CONFIG to a non-existent file so YAML path is skipped
        monkeypatch.setenv("JIRA_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.setenv("JIRA_PAT", "env_pat")
        monkeypatch.setenv("JIRA_BASE_URL", "https://env-jira.example.com")

        cfg = load_config()

        assert cfg.personal_access_token == "env_pat"
        assert cfg.base_url == "https://env-jira.example.com"
        assert cfg.allowed_project_keys == []
        assert cfg.default_user == ""


class TestMissingCredentials:
    def test_no_config_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_CONFIG", str(tmp_path / "nonexistent.yaml"))
        monkeypatch.delenv("JIRA_PAT", raising=False)
        monkeypatch.delenv("JIRA_BASE_URL", raising=False)

        with pytest.raises(ValueError, match="Jira config not found"):
            load_config()


class TestSingletonCaching:
    def test_returns_same_instance_on_second_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "jira.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "personal_access_token": "pat",
                    "base_url": "https://jira.example.com",
                }
            )
        )
        monkeypatch.setenv("JIRA_CONFIG", str(config_file))

        first = load_config()
        second = load_config()

        assert first is second
