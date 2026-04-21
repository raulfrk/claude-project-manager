"""Tests for installer.local_marketplace — local clone management."""

from __future__ import annotations

from pathlib import Path


class TestConstants:
    def test_local_clone_dir_is_user_cache(self):
        from installer.local_marketplace import LOCAL_CLONE_DIR

        assert (
            LOCAL_CLONE_DIR
            == Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"
        )

    def test_https_source_is_github_https_url(self):
        from installer.local_marketplace import _HTTPS_SOURCE

        assert _HTTPS_SOURCE == "https://github.com/raulfrk/claude-project-manager.git"

    def test_git_timeout_is_positive(self):
        from installer.local_marketplace import _GIT_TIMEOUT

        assert _GIT_TIMEOUT > 0
