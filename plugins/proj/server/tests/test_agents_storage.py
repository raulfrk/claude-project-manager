"""Tests for agents storage functions in server.lib.storage."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib import storage
from server.lib.models import ProjConfig


@pytest.fixture()
def tmp_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(cfg)
    return cfg


def _make_project_dir(cfg: ProjConfig, project_name: str) -> Path:
    proj_dir = Path(cfg.tracking_dir) / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir


def test_agents_path_correct(tmp_cfg: ProjConfig) -> None:
    path = storage.agents_path(tmp_cfg, "myapp")
    expected = Path(tmp_cfg.tracking_dir) / "myapp" / "agents.yaml"
    assert path == expected


def test_load_agents_missing_file(tmp_cfg: ProjConfig) -> None:
    _make_project_dir(tmp_cfg, "myapp")
    # No agents.yaml written — file does not exist
    result = storage.load_agents(tmp_cfg, "myapp")
    assert result == {}


def test_load_agents_empty_file(tmp_cfg: ProjConfig) -> None:
    proj_dir = _make_project_dir(tmp_cfg, "myapp")
    # Write an empty file (yaml.safe_load returns None for empty content)
    (proj_dir / "agents.yaml").write_text("")
    result = storage.load_agents(tmp_cfg, "myapp")
    assert result == {}


def test_load_agents_valid_content(tmp_cfg: ProjConfig) -> None:
    proj_dir = _make_project_dir(tmp_cfg, "myapp")
    data = {
        "version": 1,
        "agents": {
            "define": "MyPlanAgent",
            "research": None,
            "decompose": None,
            "execute": None,
        },
    }
    (proj_dir / "agents.yaml").write_text(yaml.dump(data))
    result = storage.load_agents(tmp_cfg, "myapp")
    assert result["version"] == 1
    assert isinstance(result["agents"], dict)
    agents_section = result["agents"]
    assert isinstance(agents_section, dict)
    assert agents_section["define"] == "MyPlanAgent"
    assert agents_section["research"] is None


def test_save_and_load_agents_roundtrip(tmp_cfg: ProjConfig) -> None:
    _make_project_dir(tmp_cfg, "myapp")
    original: dict[str, object] = {
        "version": 1,
        "agents": {
            "define": "CustomDefine",
            "research": "CustomResearch",
            "decompose": None,
            "execute": None,
        },
    }
    storage.save_agents(tmp_cfg, "myapp", original)
    loaded = storage.load_agents(tmp_cfg, "myapp")
    assert loaded["version"] == 1
    agents_section = loaded["agents"]
    assert isinstance(agents_section, dict)
    assert agents_section["define"] == "CustomDefine"
    assert agents_section["research"] == "CustomResearch"
    assert agents_section["decompose"] is None
    assert agents_section["execute"] is None
