"""Tests for the caveman-experiment branch-aware claudemd helpers.

Covers :func:`build_managed_section` variant selection, sidecar backup
magic-header handling, restore-with-user-edit preservation, and the
branch detection edge case around detached HEAD.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from installer.claudemd import (
    CAVEMAN_SIDECAR_HEADER_PREFIX,
    MARKER_END,
    MARKER_START,
    _backup_global_claudemd_for_caveman,
    _MANAGED_SECTION_DEFAULT,
    _restore_global_claudemd_from_caveman,
    _sidecar_header_for_now,
    _sidecar_path_for,
    build_managed_section,
    ensure_managed_section,
)

# The branch-aware helper lives under plugins/proj/... which is not on
# sys.path. Load it by file path so the test exercises the real module
# without depending on repo-layout import tricks.
_HELPER_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "proj"
    / "server"
    / "server"
    / "scripts"
    / "claudemd_branch_aware.py"
)


def _load_helper() -> ModuleType:
    mod_name = "claudemd_branch_aware_test_load"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so dataclass annotation resolution can find the
    # module via cls.__module__ lookup (required under
    # ``from __future__ import annotations``).
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


class TestBuildManagedSection:
    def test_build_managed_section_default_on_dev(self):
        section = build_managed_section(
            project_name="claude-project-manager",
            current_branch="dev",
        )
        assert section == _MANAGED_SECTION_DEFAULT
        assert "Caveman-Aware Output" not in section

    def test_build_managed_section_caveman_on_dev_caveman(self):
        section = build_managed_section(
            project_name="claude-project-manager",
            current_branch="dev-caveman",
        )
        # The caveman variant splices _CAVEMAN_APPEND inside the markers,
        # so _MANAGED_SECTION_DEFAULT is NOT a substring of the caveman
        # variant — only the inner content (without MARKER_END) is shared.
        assert section.startswith(MARKER_START)
        assert section.endswith(MARKER_END)
        assert "Caveman-Aware Output" in section
        assert "TeamCreate" in section  # default rules still present
        assert "AskUserQuestion" in section
        # The default variant (marker-wrapped) must not appear verbatim
        # because _CAVEMAN_APPEND is spliced in before MARKER_END.
        assert _MANAGED_SECTION_DEFAULT not in section

    def test_build_managed_section_other_project_unaffected(self):
        # Even on a caveman-named branch, a different project gets default.
        section = build_managed_section(
            project_name="some-other-project",
            current_branch="dev-caveman",
        )
        assert section == _MANAGED_SECTION_DEFAULT
        assert "Caveman-Aware Output" not in section

    def test_build_managed_section_with_feature_branch_under_caveman(self):
        # Glob "*caveman*" should match "feature-caveman-x" as well.
        section = build_managed_section(
            project_name="claude-project-manager",
            current_branch="feature-caveman-x",
        )
        assert "Caveman-Aware Output" in section

    def test_build_managed_section_with_none_branch(self):
        section = build_managed_section(
            project_name="claude-project-manager",
            current_branch=None,
        )
        assert section == _MANAGED_SECTION_DEFAULT


class TestSidecarBackup:
    def test_backup_creates_sidecar_with_magic_header(self, tmp_path: Path):
        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)  # seed a default file
        original_content = claude_md.read_text(encoding="utf-8")

        sidecar = _backup_global_claudemd_for_caveman(claude_md)

        assert sidecar == _sidecar_path_for(claude_md)
        assert sidecar.exists()
        sidecar_content = sidecar.read_text(encoding="utf-8")
        assert sidecar_content.startswith(CAVEMAN_SIDECAR_HEADER_PREFIX)
        # The original content is preserved below the header
        assert original_content in sidecar_content

    def test_backup_fails_loud_on_wrong_header(self, tmp_path: Path):
        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)
        # Pre-existing sidecar with the WRONG header
        sidecar = _sidecar_path_for(claude_md)
        sidecar.write_text("# NOT-OUR-HEADER\ngarbage\n", encoding="utf-8")

        with pytest.raises(ValueError, match="unexpected header"):
            _backup_global_claudemd_for_caveman(claude_md)

    def test_backup_idempotent_with_valid_existing_sidecar(self, tmp_path: Path):
        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)

        first = _backup_global_claudemd_for_caveman(claude_md)
        first_content = first.read_text(encoding="utf-8")

        # Mutate CLAUDE.md and re-run backup — sidecar must not change
        # (earliest pre-caveman snapshot is what we want to preserve).
        claude_md.write_text("DIFFERENT\n", encoding="utf-8")
        second = _backup_global_claudemd_for_caveman(claude_md)
        assert first == second
        assert second.read_text(encoding="utf-8") == first_content


class TestRestoreFromCaveman:
    def test_restore_preserves_user_non_managed_edits(self, tmp_path: Path):
        claude_md = tmp_path / "CLAUDE.md"
        user_header = "# My Notes\n\nThings I care about.\n\n"
        user_footer = "\n\n## Trailing personal section\n\nMore stuff.\n"
        # File with user content before and after a caveman-variant managed section
        caveman_section = build_managed_section(
            project_name="claude-project-manager",
            current_branch="dev-caveman",
        )
        claude_md.write_text(
            user_header + caveman_section + user_footer, encoding="utf-8"
        )

        # Create a sidecar with the magic header (content body is unused by
        # restore — restore installs the current default section).
        sidecar = _sidecar_path_for(claude_md)
        sidecar.write_text(
            _sidecar_header_for_now() + "original body (ignored by restore)\n",
            encoding="utf-8",
        )

        modified = _restore_global_claudemd_from_caveman(claude_md)
        assert modified is True

        restored = claude_md.read_text(encoding="utf-8")
        # User content in non-managed regions survives verbatim
        assert "# My Notes" in restored
        assert "Things I care about." in restored
        assert "Trailing personal section" in restored
        assert "More stuff." in restored
        # Managed section is now the default variant (no caveman append)
        assert MARKER_START in restored
        assert MARKER_END in restored
        assert "Caveman-Aware Output" not in restored
        assert "TeamCreate" in restored  # default rules present

    def test_restore_idempotent(self, tmp_path: Path):
        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)
        sidecar = _sidecar_path_for(claude_md)
        sidecar.write_text(_sidecar_header_for_now() + "whatever\n", encoding="utf-8")
        # First restore is a no-op (file already matches default)
        assert _restore_global_claudemd_from_caveman(claude_md) is False
        # Second restore also no-op
        assert _restore_global_claudemd_from_caveman(claude_md) is False

    def test_restore_raises_when_sidecar_missing(self, tmp_path: Path):
        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)
        with pytest.raises(FileNotFoundError):
            _restore_global_claudemd_from_caveman(claude_md)

    def test_restore_raises_on_sidecar_wrong_header(self, tmp_path: Path):
        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)
        sidecar = _sidecar_path_for(claude_md)
        sidecar.write_text("# NOT-CPM-HEADER\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unexpected header"):
            _restore_global_claudemd_from_caveman(claude_md)


class TestBranchDetectionDetachedHead:
    """The branch-aware helper must NO-OP (not raise) on detached HEAD.

    This exercises the contract that
    :mod:`plugins.proj.server.server.scripts.claudemd_branch_aware`
    relies on when shelling out to ``git symbolic-ref --short HEAD``.
    A detached HEAD causes symbolic-ref to exit non-zero; the script
    treats this as a no-op and preserves the current managed section.
    """

    def test_branch_detection_detached_head_fails_noop(self, tmp_path: Path):
        helper = _load_helper()

        # Simulate detached HEAD: symbolic-ref exits 128.
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0] if args else [],
                returncode=128,
                stdout=b"",
                stderr=b"fatal: ref HEAD is not a symbolic ref\n",
            )

        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)
        before = claude_md.read_text(encoding="utf-8")

        with patch.object(helper.subprocess, "run", side_effect=fake_run):
            result = helper.sync_claude_md(
                claude_md_path=claude_md,
                project_name="claude-project-manager",
                repo_root=tmp_path,
            )

        # Contract: no-op on detached HEAD, return SyncResult with status NOOP.
        assert result.status == "noop"
        assert claude_md.read_text(encoding="utf-8") == before

    def test_branch_detection_git_missing_fails_noop(self, tmp_path: Path):
        helper = _load_helper()

        def fake_run(*args, **kwargs):
            raise FileNotFoundError("git not found")

        claude_md = tmp_path / "CLAUDE.md"
        ensure_managed_section(claude_md)
        before = claude_md.read_text(encoding="utf-8")

        with patch.object(helper.subprocess, "run", side_effect=fake_run):
            result = helper.sync_claude_md(
                claude_md_path=claude_md,
                project_name="claude-project-manager",
                repo_root=tmp_path,
            )

        assert result.status == "noop"
        assert result.branch is None
        assert claude_md.read_text(encoding="utf-8") == before
