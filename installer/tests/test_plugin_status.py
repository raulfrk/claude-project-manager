"""Tests for ``installer.plugin_status``."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from installer.errors import InstallerError
from installer.plugin_status import build_plugin_status_list


def _write_marketplace(path: Path, plugins: list[dict]) -> None:
    path.write_text(json.dumps({"plugins": plugins}), encoding="utf-8")


def _write_installed(cache_dir: Path, name: str, version: str) -> None:
    plugin_dir = cache_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )


@pytest.fixture()
def marketplace(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace.json"
    _write_marketplace(
        path,
        [
            {"name": "router", "version": "2.0.0"},
            {"name": "proj", "version": "4.0.0"},
            {"name": "trello", "version": "3.0.0"},
        ],
    )
    return path


@pytest.fixture()
def cache_dir(tmp_path: Path) -> Path:
    path = tmp_path / "cache"
    path.mkdir()
    return path


def test_build_status_list_marketplace_only(
    marketplace: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing installed -> all plugins are 'available'."""
    monkeypatch.setattr("installer.plugin_status.get_installed_plugins", lambda: [])
    result = build_plugin_status_list(marketplace_path=marketplace, cache_dir=cache_dir)

    assert [s.name for s in result] == ["proj", "router", "trello"]
    for status in result:
        assert status.state == "available"
        assert status.installed_version is None


def test_build_status_list_same_version(
    marketplace: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed at matching version -> 'installed'."""
    _write_installed(cache_dir, "router", "2.0.0")
    monkeypatch.setattr(
        "installer.plugin_status.get_installed_plugins",
        lambda: ["router@claude-project-manager"],
    )
    monkeypatch.setattr(
        "installer.update.get_installed_plugin_versions",
        lambda: {"router": "2.0.0"},
    )
    result = build_plugin_status_list(marketplace_path=marketplace, cache_dir=cache_dir)

    router = next(s for s in result if s.name == "router")
    assert router.state == "installed"
    assert router.installed_version == "2.0.0"
    assert router.available_version == "2.0.0"


def test_build_status_list_different_version(
    marketplace: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed at older version -> 'outdated'."""
    _write_installed(cache_dir, "proj", "3.5.0")
    monkeypatch.setattr(
        "installer.plugin_status.get_installed_plugins",
        lambda: ["proj@claude-project-manager"],
    )
    monkeypatch.setattr(
        "installer.update.get_installed_plugin_versions",
        lambda: {"proj": "3.5.0"},
    )
    result = build_plugin_status_list(marketplace_path=marketplace, cache_dir=cache_dir)

    proj = next(s for s in result if s.name == "proj")
    assert proj.state == "outdated"
    assert proj.installed_version == "3.5.0"
    assert proj.available_version == "4.0.0"


def test_build_status_list_corrupt_plugin_version(
    marketplace: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed plugin with unreadable plugin.json -> 'outdated' + warning."""
    (cache_dir / "proj").mkdir()  # no plugin.json
    monkeypatch.setattr(
        "installer.plugin_status.get_installed_plugins",
        lambda: ["proj@claude-project-manager"],
    )
    monkeypatch.setattr(
        "installer.update.get_installed_plugin_versions",
        lambda: {},
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = build_plugin_status_list(
            marketplace_path=marketplace, cache_dir=cache_dir
        )

    proj = next(s for s in result if s.name == "proj")
    assert proj.state == "outdated"
    assert proj.installed_version is None
    assert any("plugin.json could not be read" in str(w.message) for w in caught)


def test_build_status_list_orphan_installed(
    marketplace: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed plugin that isn't in marketplace -> excluded + warning."""
    monkeypatch.setattr(
        "installer.plugin_status.get_installed_plugins",
        lambda: ["mystery@claude-project-manager"],
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = build_plugin_status_list(
            marketplace_path=marketplace, cache_dir=cache_dir
        )

    names = [s.name for s in result]
    assert "mystery" not in names
    assert any("not in the marketplace" in str(w.message) for w in caught)


def test_build_status_list_invalid_plugin_name(
    tmp_path: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid marketplace plugin name -> ValueError."""
    path = tmp_path / "marketplace.json"
    _write_marketplace(
        path,
        [
            {"name": "bad name!", "version": "1.0.0"},
        ],
    )
    monkeypatch.setattr("installer.plugin_status.get_installed_plugins", lambda: [])

    with pytest.raises(ValueError, match="Invalid plugin name"):
        build_plugin_status_list(marketplace_path=path, cache_dir=cache_dir)


def test_build_status_list_plugin_cli_failure(
    marketplace: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``get_installed_plugins`` raising InstallerError -> marketplace-only result."""

    def _raise() -> list[str]:
        raise InstallerError("claude CLI not available")

    monkeypatch.setattr("installer.plugin_status.get_installed_plugins", _raise)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = build_plugin_status_list(
            marketplace_path=marketplace, cache_dir=cache_dir
        )

    assert len(result) == 3
    assert all(s.state == "available" for s in result)
    assert any("Could not list installed plugins" in str(w.message) for w in caught)
