"""Tests for server.lib.sockets_cleanup."""

from __future__ import annotations

import json

from server.lib.sockets_cleanup import (
    KNOWN_MANAGED_PLUGINS,
    _load_installed,
    sockets_cleanup_stale,
)


class TestLoadInstalled:
    def test_dict_with_plugins_dict(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({"plugins": {"proj@cpm": {}, "router@cpm": {}}}))
        result = _load_installed(path)
        assert result == {"proj", "router"}

    def test_dict_with_plugins_list(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({"plugins": [{"name": "proj"}, {"name": "router"}]}))
        result = _load_installed(path)
        assert result == {"proj", "router"}

    def test_invalid_json_returns_none(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text("not json")
        assert _load_installed(path) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert _load_installed(tmp_path / "nope.json") is None

    def test_strips_marketplace_suffix(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({"plugins": {"proj@claude-project-manager": {}}}))
        result = _load_installed(path)
        assert result == {"proj"}


class TestSocketsCleanupStale:
    def test_removes_stale_managed_plugin(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").write_text("")
        (sockets / "proj").write_text("")

        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {"proj@cpm": {}}}))

        removed = sockets_cleanup_stale(sockets, installed)
        assert "hooks" in removed
        assert not (sockets / "hooks").exists()
        assert (sockets / "proj").exists()

    def test_ignores_non_managed_files(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "custom-plugin").write_text("")

        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {}}))

        removed = sockets_cleanup_stale(sockets, installed)
        assert removed == []
        assert (sockets / "custom-plugin").exists()

    def test_ignores_directories(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").mkdir()

        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {}}))

        removed = sockets_cleanup_stale(sockets, installed)
        assert removed == []

    def test_missing_sockets_dir(self, tmp_path):
        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {}}))
        assert sockets_cleanup_stale(tmp_path / "no-such", installed) == []

    def test_missing_installed_json(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        assert sockets_cleanup_stale(sockets, tmp_path / "nope.json") == []

    def test_unparseable_installed_json_aborts(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").write_text("")

        installed = tmp_path / "installed.json"
        installed.write_text("not json")

        removed = sockets_cleanup_stale(sockets, installed)
        assert removed == []
        assert (sockets / "hooks").exists()


class TestKnownManagedPlugins:
    def test_contains_expected_names(self):
        for name in (
            "hooks",
            "perms",
            "router",
            "sandbox",
            "proj",
            "worktree",
            "trello",
            "jira",
            "todoist",
        ):
            assert name in KNOWN_MANAGED_PLUGINS
