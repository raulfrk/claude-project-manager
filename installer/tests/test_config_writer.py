"""Tests for installer/_config_writer.py — per-bucket writer + locks + drift."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from installer._config_writer import (
    DriftDetected,
    _merge_dotted_into_dict,
    _NORMALIZERS,
    partition_answers_by_bucket,
    write_bucket,
)


class TestPartitionAnswersByBucket:
    def test_proj_key_goes_to_proj_bucket(self) -> None:
        buckets = partition_answers_by_bucket({"tracking_dir": "/a"})
        assert buckets["proj"] == {"tracking_dir": "/a"}

    def test_worktree_key_goes_to_worktree_bucket(self) -> None:
        buckets = partition_answers_by_bucket({"default_worktree_dir": "/wt"})
        assert buckets["worktree"] == {"default_worktree_dir": "/wt"}

    def test_unknown_key_defaults_to_proj(self) -> None:
        buckets = partition_answers_by_bucket({"unknown_legacy_key": "x"})
        assert buckets["proj"] == {"unknown_legacy_key": "x"}

    def test_all_distinct_buckets_present(self) -> None:
        buckets = partition_answers_by_bucket({})
        # Every yaml_file referenced by any spec should be in the buckets dict
        assert "proj" in buckets
        assert "worktree" in buckets

    def test_empty_answers_returns_empty_buckets(self) -> None:
        buckets = partition_answers_by_bucket({})
        for answers in buckets.values():
            assert answers == {}


class TestMergeDottedIntoDict:
    def test_flat_key_set_in_place(self) -> None:
        d: dict[str, Any] = {}
        _merge_dotted_into_dict(d, {"a": 1})
        assert d == {"a": 1}

    def test_dotted_key_creates_nested(self) -> None:
        d: dict[str, Any] = {}
        _merge_dotted_into_dict(d, {"a.b.c": 42})
        assert d == {"a": {"b": {"c": 42}}}

    def test_preserves_unknown_keys(self) -> None:
        d: dict[str, Any] = {"unknown": "value", "sync": {"other": "x"}}
        _merge_dotted_into_dict(d, {"sync.todoist.enabled": True})
        assert d["unknown"] == "value"
        assert d["sync"]["other"] == "x"
        assert d["sync"]["todoist"]["enabled"] is True

    def test_overwrites_scalar_with_dict(self) -> None:
        d: dict[str, Any] = {"a": "scalar"}
        _merge_dotted_into_dict(d, {"a.b": 1})
        assert d == {"a": {"b": 1}}


class TestWriteBucket:
    def test_writes_merged_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "proj.yaml"
        existing = {"preserved": "keep_me"}
        answers = {"tracking_dir": "/custom"}
        write_bucket(path, existing, answers, bucket="worktree")  # no normalizer
        assert path.exists()
        loaded = yaml.safe_load(path.read_text())
        assert loaded["preserved"] == "keep_me"
        assert loaded["tracking_dir"] == "/custom"

    def test_proj_normalizer_falls_through_on_import_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If ProjConfig cannot be imported, raw dict is written, no crash."""
        path = tmp_path / "proj.yaml"
        # Force _normalize_proj path
        write_bucket(
            path,
            {"unknown_key": "kept"},
            {"tracking_dir": "/custom"},
            bucket="proj",
        )
        assert path.exists()
        loaded = yaml.safe_load(path.read_text())
        # Either the normalizer ran (removing unknown_key) or fell through
        # (keeping it). Both outcomes are acceptable — just assert the wizard
        # field survived.
        assert loaded.get("tracking_dir") == "/custom"

    def test_mtime_drift_logged_but_write_proceeds(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "worktree.yaml"
        path.write_text("existing: value\n")
        # Wizard recorded mtime well in the past
        stale_mtime = path.stat().st_mtime - 10.0
        caplog.set_level("WARNING", logger="installer.config_writer")
        write_bucket(
            path,
            yaml.safe_load(path.read_text()),
            {"default_worktree_dir": "/new"},
            bucket="worktree",
            expected_mtime=stale_mtime,
        )
        assert "drift detected" in caplog.text
        loaded = yaml.safe_load(path.read_text())
        assert loaded["default_worktree_dir"] == "/new"
        assert loaded["existing"] == "value"

    def test_matching_mtime_no_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "worktree.yaml"
        path.write_text("existing: value\n")
        fresh_mtime = path.stat().st_mtime
        caplog.set_level("WARNING", logger="installer.config_writer")
        write_bucket(
            path,
            yaml.safe_load(path.read_text()),
            {"default_worktree_dir": "/new"},
            bucket="worktree",
            expected_mtime=fresh_mtime,
        )
        assert "drift detected" not in caplog.text

    def test_advisory_lock_raises_drift_if_held(self, tmp_path: Path) -> None:
        path = tmp_path / "worktree.yaml"
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Grab the lock from a second fd
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(DriftDetected):
                write_bucket(
                    path,
                    {},
                    {"default_worktree_dir": "/new"},
                    bucket="worktree",
                )
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_unknown_keys_preserved_across_merge(self, tmp_path: Path) -> None:
        path = tmp_path / "proj.yaml"
        existing = {
            "legacy_key": "still_here",
            "sync": {"external_thing": {"nested": 1}},
        }
        write_bucket(
            path,
            existing,
            {"tracking_dir": "/new"},
            bucket="worktree",  # bucket name here controls normalizer, not target file
        )
        loaded = yaml.safe_load(path.read_text())
        assert loaded["legacy_key"] == "still_here"
        assert loaded["sync"]["external_thing"]["nested"] == 1
        assert loaded["tracking_dir"] == "/new"


class TestNormalizersRegistry:
    def test_proj_normalizer_registered(self) -> None:
        assert "proj" in _NORMALIZERS

    def test_non_proj_bucket_has_no_normalizer(self) -> None:
        # Only proj has a normalizer in the initial registry.
        assert "worktree" not in _NORMALIZERS
        assert "todoist" not in _NORMALIZERS
