"""Tests for scripts/check_shared_version.py."""

from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import check_shared_version


def make_run_result(stdout: str = "", returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


PYPROJECT_V1 = '[project]\nname = "foo"\nversion = "0.4.0"\n'
PYPROJECT_V2 = '[project]\nname = "foo"\nversion = "0.5.0"\n'


class TestGetStagedFiles:
    def test_returns_list_of_lines(self) -> None:
        with patch(
            "subprocess.run", return_value=make_run_result("a.py\nb.py\n")
        ) as mock_run:
            result = check_shared_version.get_staged_files()
        assert result == ["a.py", "b.py"]
        mock_run.assert_called_once_with(
            ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
        )

    def test_empty_stdout_returns_empty_list(self) -> None:
        with patch("subprocess.run", return_value=make_run_result("")):
            result = check_shared_version.get_staged_files()
        assert result == []


class TestGetVersionFromGit:
    def test_parses_version_single_quotes(self) -> None:
        content = "[project]\nversion = '1.2.3'\n"
        with patch("subprocess.run", return_value=make_run_result(content)):
            assert check_shared_version.get_version_from_git(":") == "1.2.3"

    def test_parses_version_double_quotes(self) -> None:
        content = '[project]\nversion = "0.4.0"\n'
        with patch("subprocess.run", return_value=make_run_result(content)):
            assert check_shared_version.get_version_from_git(":") == "0.4.0"

    def test_returns_none_on_nonzero_returncode(self) -> None:
        with patch("subprocess.run", return_value=make_run_result("", returncode=128)):
            assert check_shared_version.get_version_from_git("HEAD:") is None

    def test_returns_none_when_version_not_found(self) -> None:
        with patch(
            "subprocess.run", return_value=make_run_result("[project]\nname = 'foo'\n")
        ):
            assert check_shared_version.get_version_from_git(":") is None


class TestExtractTransportVersion:
    """Extract claude-hook-transport version from uv.lock content (root + plugin locks)."""

    def test_finds_version_in_plugin_lock_block(self) -> None:
        """Root-style lock: claude-hook-transport appears as a directory-sourced package."""
        content = (
            "[[package]]\n"
            'name = "claude-hook-transport"\n'
            'version = "0.4.11"\n'
            'source = { directory = "plugins/_shared" }\n'
        )
        assert check_shared_version._extract_transport_version(content) == "0.4.11"

    def test_finds_version_as_project_in_shared_lock(self) -> None:
        """plugins/_shared/uv.lock declares the package as its own [[package]] too."""
        content = (
            "[[package]]\n"
            'name = "claude-hook-transport"\n'
            'version = "0.4.11"\n'
            'source = { editable = "." }\n'
        )
        assert check_shared_version._extract_transport_version(content) == "0.4.11"

    def test_returns_none_when_package_missing(self) -> None:
        content = '[[package]]\nname = "httpx"\nversion = "0.28.1"\n'
        assert check_shared_version._extract_transport_version(content) is None

    def test_picks_claude_hook_transport_block_not_sibling(self) -> None:
        """Must match the block with name = claude-hook-transport, ignore others that appear first."""
        content = (
            "[[package]]\n"
            'name = "httpx"\n'
            'version = "0.28.1"\n'
            "\n"
            "[[package]]\n"
            'name = "claude-hook-transport"\n'
            'version = "0.4.11"\n'
        )
        assert check_shared_version._extract_transport_version(content) == "0.4.11"

    def test_ignores_version_line_that_precedes_name(self) -> None:
        """Block where version appears before name must still be parsed correctly (pairs by block)."""
        content = '[[package]]\nversion = "0.4.11"\nname = "claude-hook-transport"\n'
        assert check_shared_version._extract_transport_version(content) == "0.4.11"

    def test_ignores_dependency_references_in_other_packages(self) -> None:
        """Dep-table entries `{ name = "claude-hook-transport" }` in OTHER packages must not match."""
        content = (
            "[[package]]\n"
            'name = "anyio"\n'
            'version = "4.0.0"\n'
            'dependencies = [{ name = "claude-hook-transport" }]\n'
            "\n"
            "[[package]]\n"
            'name = "claude-hook-transport"\n'
            'version = "0.4.11"\n'
        )
        assert check_shared_version._extract_transport_version(content) == "0.4.11"


class TestMain:
    def test_no_shared_py_staged_exits_0(self) -> None:
        """When no plugins/_shared/*.py files are staged, skip the check."""
        staged = ["plugins/proj/server/server/main.py", "README.md"]
        with patch("check_shared_version.get_staged_files", return_value=staged):
            assert check_shared_version.main() == 0

    def test_test_only_changes_in_shared_do_not_trigger_gate(self) -> None:
        """712: plugins/_shared/tests/**/*.py changes should not require a version bump."""
        staged = [
            "plugins/_shared/tests/test_managed_section.py",
            "plugins/_shared/tests/test_scrubbing.py",
        ]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch("check_shared_version.get_version_from_git") as mock_get,
        ):
            result = check_shared_version.main()
        assert result == 0
        mock_get.assert_not_called()  # no version check when only tests changed

    def test_source_plus_tests_staged_still_triggers_gate(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """712: mixed source + tests staged → source wins, gate fires as normal."""
        staged = [
            "plugins/_shared/tests/test_managed_section.py",
            "plugins/_shared/hook_dispatch/dispatch.py",
        ]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git",
                side_effect=["0.4.10", "0.4.10"],
            ),
        ):
            result = check_shared_version.main()
        assert result == 1  # version not bumped → gate blocks
        captured = capsys.readouterr()
        assert "version not bumped" in captured.out

    def test_shared_py_staged_version_bumped_exits_0(self) -> None:
        """When _shared .py staged and version has changed, allow the commit."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git",
                side_effect=["0.5.0", "0.4.0"],
            ),
            patch(
                "check_shared_version._check_lockfiles_pin_new_version",
                return_value=[],
            ),
        ):
            assert check_shared_version.main() == 0

    def test_shared_py_staged_version_not_bumped_exits_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When _shared .py staged and version unchanged, fail the commit."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git",
                side_effect=["0.4.0", "0.4.0"],
            ),
        ):
            result = check_shared_version.main()
        assert result == 1
        captured = capsys.readouterr()
        assert "version not bumped" in captured.out
        assert "0.4.0" in captured.out

    def test_shared_py_staged_no_head_version_exits_0(self) -> None:
        """When HEAD has no version (initial commit), skip the check."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        # staged_version first, head_version second
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git", side_effect=["0.4.0", None]
            ),
        ):
            assert check_shared_version.main() == 0

    def test_shared_py_staged_no_staged_pyproject_exits_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When pyproject.toml not in staged index, report error."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git", side_effect=[None, "0.4.0"]
            ),
        ):
            result = check_shared_version.main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Cannot verify version bump" in captured.out

    def test_bump_with_all_locks_in_sync_exits_0(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Version bumped and every lockfile pins the new version → pass."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git",
                side_effect=["0.4.11", "0.4.10"],
            ),
            patch(
                "check_shared_version._check_lockfiles_pin_new_version",
                return_value=[],
            ),
        ):
            assert check_shared_version.main() == 0

    def test_bump_with_drifted_lock_exits_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Version bumped but at least one lockfile is stale → fail with named drifts."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        drift = [
            ("uv.lock", "0.4.11", "0.4.10"),
            ("plugins/proj/server/uv.lock", "0.4.11", None),
        ]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git",
                side_effect=["0.4.11", "0.4.10"],
            ),
            patch(
                "check_shared_version._check_lockfiles_pin_new_version",
                return_value=drift,
            ),
        ):
            result = check_shared_version.main()
        assert result == 1
        captured = capsys.readouterr()
        assert "uv.lock" in captured.out
        assert "plugins/proj/server/uv.lock" in captured.out
        assert "0.4.11" in captured.out
        assert "0.4.10" in captured.out
        assert "just sync" in captured.out  # remediation hint

    def test_no_bump_skips_lockfile_check(self) -> None:
        """Path where version is unchanged — existing error path unchanged, lockfile check NOT invoked."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git",
                side_effect=["0.4.10", "0.4.10"],
            ),
            patch(
                "check_shared_version._check_lockfiles_pin_new_version",
            ) as mock_lock_check,
        ):
            result = check_shared_version.main()
        assert result == 1  # unchanged: existing "version not bumped" path
        mock_lock_check.assert_not_called()


class TestCheckLockfilesPinNewVersion:
    """Validate every declared lockfile references the new claude-hook-transport version."""

    def test_all_lockfiles_reference_new_version_returns_empty(
        self,
    ) -> None:
        """When every lockfile pins the new version, the check returns an empty drift list."""
        new_version = "0.4.11"
        good_content = (
            f'[[package]]\nname = "claude-hook-transport"\nversion = "{new_version}"\n'
        )

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            # cmd == ["git", "show", ":path/to/uv.lock"]
            return make_run_result(good_content, returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            drift = check_shared_version._check_lockfiles_pin_new_version(new_version)
        assert drift == []

    def test_one_lockfile_has_old_version_returned_as_drift(self) -> None:
        new_version = "0.4.11"
        good_content = (
            f'[[package]]\nname = "claude-hook-transport"\nversion = "{new_version}"\n'
        )
        old_content = (
            '[[package]]\nname = "claude-hook-transport"\nversion = "0.4.10"\n'
        )
        stale_path = check_shared_version.LOCKFILES[1]  # plugins/_shared/uv.lock

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            path = cmd[2].lstrip(":")
            if path == stale_path:
                return make_run_result(old_content, returncode=0)
            return make_run_result(good_content, returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            drift = check_shared_version._check_lockfiles_pin_new_version(new_version)
        assert len(drift) == 1
        path, expected, actual = drift[0]
        assert expected == "0.4.11"
        assert actual == "0.4.10"
        assert path == stale_path

    def test_missing_lockfile_returned_as_drift(self) -> None:
        """git show returns non-zero → treat as missing-from-index."""
        new_version = "0.4.11"
        good_content = (
            f'[[package]]\nname = "claude-hook-transport"\nversion = "{new_version}"\n'
        )
        missing_path = check_shared_version.LOCKFILES[
            2
        ]  # plugins/router/server/uv.lock

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            path = cmd[2].lstrip(":")
            if path == missing_path:
                return make_run_result("", returncode=128)
            return make_run_result(good_content, returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            drift = check_shared_version._check_lockfiles_pin_new_version(new_version)
        assert len(drift) == 1
        path, expected, actual = drift[0]
        assert expected == "0.4.11"
        assert actual is None  # sentinel for missing
        assert path == missing_path

    def test_lockfile_without_transport_package_returned_as_drift(self) -> None:
        new_version = "0.4.11"
        good_content = (
            f'[[package]]\nname = "claude-hook-transport"\nversion = "{new_version}"\n'
        )
        bogus_content = '[[package]]\nname = "httpx"\nversion = "0.28.1"\n'
        bogus_path = check_shared_version.LOCKFILES[3]  # plugins/proj/server/uv.lock

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            path = cmd[2].lstrip(":")
            if path == bogus_path:
                return make_run_result(bogus_content, returncode=0)
            return make_run_result(good_content, returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            drift = check_shared_version._check_lockfiles_pin_new_version(new_version)
        assert len(drift) == 1
        path, expected, actual = drift[0]
        assert expected == "0.4.11"
        assert actual is None
        assert path == bogus_path


class TestLockfilesRoster:
    """Pin the LOCKFILES roster so a new plugin addition that forgets to extend it fails here."""

    def test_lockfiles_roster_is_exhaustive(self) -> None:
        expected = {
            "uv.lock",
            "plugins/_shared/uv.lock",
            "plugins/router/server/uv.lock",
            "plugins/proj/server/uv.lock",
            "plugins/worktree/server/uv.lock",
            "plugins/todoist/server/uv.lock",
            "plugins/trello/server/uv.lock",
            "plugins/jira/server/uv.lock",
            "plugins/confluence/server/uv.lock",
            "plugins/wiki/server/uv.lock",
        }
        assert set(check_shared_version.LOCKFILES) == expected
