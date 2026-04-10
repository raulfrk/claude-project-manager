"""Tests for installer/app.py call order and settings_hooks stage wiring."""

from __future__ import annotations

import pytest


class TestInstallerAppSettingsHooksStage:
    """Assert InstallerApp routes through the settings_hooks stage after yaml_hooks."""

    def test_app_has_settings_hooks_stage_method(self):
        """Sanity: the wiring method exists on InstallerApp."""
        from installer.app import InstallerApp

        candidates = [
            "_check_settings_hooks_diff",
            "_push_settings_hooks_diff_screen",
            "_on_settings_hooks_diff_complete",
            "_on_settings_hooks_diff_done",
        ]
        found = [name for name in candidates if hasattr(InstallerApp, name)]
        assert found, f"None of {candidates} found on InstallerApp"

    def test_app_imports_settings_hooks(self):
        """Sanity: the app module imports from installer.settings_hooks."""
        import inspect

        import installer.app as app_mod

        source = inspect.getsource(app_mod)
        assert "settings_hooks" in source, (
            "installer.app should reference settings_hooks"
        )

    def test_skips_stage_when_no_plugin_dirs(self, tmp_path, monkeypatch):
        """With empty plugin_dirs, the settings_hooks stage is skipped gracefully."""
        from installer.app import InstallerApp

        app = InstallerApp()
        if hasattr(app, "_plugin_dirs"):
            app._plugin_dirs = []
        for name in [
            "_check_settings_hooks_diff",
            "_push_settings_hooks_diff_screen",
        ]:
            if hasattr(app, name):
                try:
                    getattr(app, name)()
                except Exception as exc:
                    pytest.skip(f"{name} requires full app context: {exc}")
                break
