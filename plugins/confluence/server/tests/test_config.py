"""Tests for confluence config loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib.config import load_config
from server.lib.errors import ConfigError


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data))


def test_load_cloud_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(
        cfg_path,
        {
            "deployment": "cloud",
            "base_url": "https://acme.atlassian.net",
            "email": "u@example.com",
            "api_token": "tok123",
            "allowed_spaces": ["DOCS"],
        },
    )

    cfg = load_config(str(cfg_path))

    assert cfg.deployment == "cloud"
    assert cfg.base_url == "https://acme.atlassian.net"
    assert cfg.email == "u@example.com"
    assert cfg.api_token == "tok123"
    assert cfg.personal_access_token is None
    assert cfg.allowed_spaces == ["DOCS"]
    assert cfg.rate_limit_per_10s == 10
    assert cfg.default_max_results == 25
    assert cfg.max_results_cap == 100
    assert cfg.timeout_seconds == 30


def test_load_server_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(
        cfg_path,
        {
            "deployment": "server",
            "base_url": "https://confluence.example.com",
            "personal_access_token": "pat-456",
        },
    )

    cfg = load_config(str(cfg_path))

    assert cfg.deployment == "server"
    assert cfg.personal_access_token == "pat-456"
    assert cfg.email is None
    assert cfg.api_token is None
    assert cfg.allowed_spaces == []


def test_base_url_trailing_slash_stripped(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(
        cfg_path,
        {
            "deployment": "server",
            "base_url": "https://confluence.example.com/",
            "personal_access_token": "pat",
        },
    )

    cfg = load_config(str(cfg_path))

    assert cfg.base_url == "https://confluence.example.com"


def test_missing_config_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(str(missing))


def test_env_var_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(
        cfg_path,
        {
            "deployment": "server",
            "base_url": "https://yaml.example.com",
            "personal_access_token": "yaml-pat",
        },
    )
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-pat")

    cfg = load_config(str(cfg_path))

    assert cfg.base_url == "https://env.example.com"
    assert cfg.personal_access_token == "env-pat"


def test_config_default_path_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(
        cfg_path,
        {
            "deployment": "server",
            "base_url": "https://x.example.com",
            "personal_access_token": "pat",
        },
    )
    monkeypatch.setenv("CONFLUENCE_CONFIG", str(cfg_path))

    cfg = load_config()

    assert cfg.base_url == "https://x.example.com"


def test_empty_allowed_spaces_defaults_to_list(tmp_path: Path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    _write_yaml(
        cfg_path,
        {
            "deployment": "server",
            "base_url": "https://x.example.com",
            "personal_access_token": "pat",
        },
    )

    cfg = load_config(str(cfg_path))

    assert cfg.allowed_spaces == []
    assert isinstance(cfg.allowed_spaces, list)
