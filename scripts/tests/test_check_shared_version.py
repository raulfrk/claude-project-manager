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


class TestMain:
    def test_no_shared_py_staged_exits_0(self) -> None:
        """When no plugins/_shared/*.py files are staged, skip the check."""
        staged = ["plugins/proj/server/server/main.py", "README.md"]
        with patch("check_shared_version.get_staged_files", return_value=staged):
            assert check_shared_version.main() == 0

    def test_shared_py_staged_version_bumped_exits_0(self) -> None:
        """When _shared .py staged and version has changed, allow the commit."""
        staged = ["plugins/_shared/hook_dispatch/dispatch.py"]
        with (
            patch("check_shared_version.get_staged_files", return_value=staged),
            patch(
                "check_shared_version.get_version_from_git",
                side_effect=["0.5.0", "0.4.0"],
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
