"""Tests for server.scripts.session_start_loader — SessionStart hook script.

Covers the detection function (`detect_project_for_cwd`) for exact matches,
walk-up subdirectory matches, multi-repo projects, archived filtering, error
paths (missing/corrupt index and meta), symlink resolution, tie-breakers, and
CLI stdout/stderr format via subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.models import ProjConfig
from server.scripts.session_start_loader import (
    WARNING_PREFIX,
    _resolve_tracking_dir,
    detect_project_for_cwd,
)
from tests.conftest import setup_project

if TYPE_CHECKING:
    import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, rel: str) -> Path:
    """Create a real directory that can serve as a project repo path."""
    p = tmp_path / rel
    p.mkdir(parents=True)
    return p


def _run_loader(
    *args: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the loader script as a subprocess."""
    server_dir = Path(__file__).parents[1]  # plugins/proj/server/
    return subprocess.run(
        [sys.executable, "-m", "server.scripts.session_start_loader", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or server_dir),
        check=False,
    )


# ---------------------------------------------------------------------------
# detect_project_for_cwd unit tests
# ---------------------------------------------------------------------------


def test_exact_match(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    result = detect_project_for_cwd(str(repo), tracking_dir=Path(cfg.tracking_dir))
    assert result == "foo"


def test_subdirectory_match(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    sub = repo / "src" / "pkg"
    sub.mkdir(parents=True)
    setup_project(cfg, "foo", str(repo))

    result = detect_project_for_cwd(str(sub), tracking_dir=Path(cfg.tracking_dir))
    assert result == "foo"


def test_parent_no_match(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    # tmp_path/repos is a parent of the registered repo — must NOT match
    parent = repo.parent
    result = detect_project_for_cwd(str(parent), tracking_dir=Path(cfg.tracking_dir))
    assert result is None


def test_no_project(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    elsewhere = _make_repo(tmp_path, "elsewhere")
    result = detect_project_for_cwd(str(elsewhere), tracking_dir=Path(cfg.tracking_dir))
    assert result is None


def test_missing_index(cfg: ProjConfig, tmp_path: Path) -> None:
    # No projects created → active-projects.yaml does not exist
    assert not (Path(cfg.tracking_dir) / "active-projects.yaml").exists()

    result = detect_project_for_cwd(str(tmp_path), tracking_dir=Path(cfg.tracking_dir))
    assert result is None


def test_malformed_index(cfg: ProjConfig, tmp_path: Path) -> None:
    tracking_dir = Path(cfg.tracking_dir)
    tracking_dir.mkdir(parents=True, exist_ok=True)
    (tracking_dir / "active-projects.yaml").write_text("this: is: not: valid: yaml: [")

    result = detect_project_for_cwd(str(tmp_path), tracking_dir=tracking_dir)
    assert result is None


def test_multi_repo_match(cfg: ProjConfig, tmp_path: Path) -> None:
    repo_a = _make_repo(tmp_path, "repos/foo-a")
    repo_b = _make_repo(tmp_path, "repos/foo-b")
    setup_project(cfg, "foo", str(repo_a))

    # Append a second repo to the meta.yaml directly.
    meta = storage.load_meta(cfg, "foo")
    from server.lib.models import RepoEntry

    meta.repos.append(RepoEntry(label="docs", path=str(repo_b)))
    storage.save_meta(cfg, meta)

    assert detect_project_for_cwd(str(repo_a), tracking_dir=Path(cfg.tracking_dir)) == "foo"
    assert detect_project_for_cwd(str(repo_b), tracking_dir=Path(cfg.tracking_dir)) == "foo"


def test_archived_not_matched(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    index = storage.load_index(cfg)
    index.projects["foo"].archived = True
    storage.save_index(cfg, index)

    result = detect_project_for_cwd(str(repo), tracking_dir=Path(cfg.tracking_dir))
    assert result is None


def test_orphaned_index_entry(
    cfg: ProjConfig,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    # Delete the meta.yaml to orphan the index entry.
    meta_path = Path(cfg.tracking_dir) / "foo" / "meta.yaml"
    meta_path.unlink()

    result = detect_project_for_cwd(str(repo), tracking_dir=Path(cfg.tracking_dir))
    assert result is None

    captured = capsys.readouterr()
    assert WARNING_PREFIX in captured.err
    assert "1 project(s) had unreadable meta.yaml" in captured.err


def test_corrupted_meta(
    cfg: ProjConfig,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    # Corrupt the meta.yaml file.
    meta_path = Path(cfg.tracking_dir) / "foo" / "meta.yaml"
    meta_path.write_text("not: valid: [yaml:")

    result = detect_project_for_cwd(str(repo), tracking_dir=Path(cfg.tracking_dir))
    assert result is None

    captured = capsys.readouterr()
    assert WARNING_PREFIX in captured.err
    assert "1 project(s) had unreadable meta.yaml" in captured.err


def test_symlink_cwd(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    link = tmp_path / "link-to-foo"
    link.symlink_to(repo)

    result = detect_project_for_cwd(str(link), tracking_dir=Path(cfg.tracking_dir))
    assert result == "foo"


def test_trailing_slash(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    # Store repo with trailing slash in meta.yaml.
    setup_project(cfg, "foo", str(repo) + "/")

    # Query with no trailing slash — both sides normalized by resolve().
    result = detect_project_for_cwd(str(repo), tracking_dir=Path(cfg.tracking_dir))
    assert result == "foo"


def test_custom_tracking_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing --tracking-dir / tracking_dir override reads index from the custom path."""
    custom_td = tmp_path / "custom-tracking"
    custom_td.mkdir()

    # Point storage at this custom dir via a temp cfg, then use setup_project.
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    custom_cfg = ProjConfig(tracking_dir=str(custom_td))
    storage.save_config(custom_cfg)

    repo = _make_repo(tmp_path, "repos/bar")
    setup_project(custom_cfg, "bar", str(repo))

    # Verify the default tracking dir is not used — point PROJ_CONFIG_PATH away.
    monkeypatch.setattr(
        "server.scripts.session_start_loader.PROJ_CONFIG_PATH",
        tmp_path / "nonexistent-proj.yaml",
    )
    # Also override DEFAULT_TRACKING_DIR so a real ~/projects/tracking is never hit.
    monkeypatch.setattr(
        "server.scripts.session_start_loader.DEFAULT_TRACKING_DIR",
        tmp_path / "nonexistent-default",
    )

    result = detect_project_for_cwd(str(repo), tracking_dir=custom_td)
    assert result == "bar"


def test_empty_cwd(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    assert detect_project_for_cwd("", tracking_dir=Path(cfg.tracking_dir)) is None


def test_tie_breaker(cfg: ProjConfig, tmp_path: Path) -> None:
    """Two projects both claim the same cwd → first in index iteration order wins."""
    repo = _make_repo(tmp_path, "repos/shared")
    setup_project(cfg, "alpha", str(repo))
    setup_project(cfg, "beta", str(repo))

    # Confirm index insertion order is alpha, beta.
    index = storage.load_index(cfg)
    assert list(index.projects.keys()) == ["alpha", "beta"]

    result = detect_project_for_cwd(str(repo), tracking_dir=Path(cfg.tracking_dir))
    assert result == "alpha"


# ---------------------------------------------------------------------------
# CLI subprocess tests
# ---------------------------------------------------------------------------


def test_cli_stdout_format(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))

    result = _run_loader(
        "--cwd",
        str(repo),
        "--tracking-dir",
        str(cfg.tracking_dir),
    )
    assert result.returncode == 0
    assert result.stdout == 'proj_load_session("foo")\n'


def test_cli_silent_on_no_match(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))
    elsewhere = _make_repo(tmp_path, "elsewhere")

    result = _run_loader(
        "--cwd",
        str(elsewhere),
        "--tracking-dir",
        str(cfg.tracking_dir),
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_cli_warning_on_orphan(cfg: ProjConfig, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "repos/foo")
    setup_project(cfg, "foo", str(repo))
    (Path(cfg.tracking_dir) / "foo" / "meta.yaml").unlink()

    result = _run_loader(
        "--cwd",
        str(repo),
        "--tracking-dir",
        str(cfg.tracking_dir),
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert WARNING_PREFIX in result.stderr
    assert "1 project(s) had unreadable meta.yaml" in result.stderr


# ── Error visibility tests ────────────────────────────────────────────────────


def test_resolve_tracking_dir_corrupt_yaml_prints_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corrupt proj.yaml triggers a stderr warning instead of silently swallowing the error."""
    from unittest.mock import patch

    corrupt_yaml = tmp_path / "proj.yaml"
    corrupt_yaml.write_text("{{invalid: yaml: [")  # intentionally malformed

    with patch("server.scripts.session_start_loader.PROJ_CONFIG_PATH", corrupt_yaml):
        result = _resolve_tracking_dir(override=None)

    # Should fall back to DEFAULT_TRACKING_DIR
    from server.scripts.session_start_loader import DEFAULT_TRACKING_DIR

    assert result == DEFAULT_TRACKING_DIR

    captured = capsys.readouterr()
    assert WARNING_PREFIX in captured.err
    assert "proj.yaml" in captured.err
