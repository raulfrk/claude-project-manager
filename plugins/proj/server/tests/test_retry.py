from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from server.lib.retry import log_orphaned_resource, retry_link

# ---------------------------------------------------------------------------
# retry_link
# ---------------------------------------------------------------------------


class TestRetryLink:
    def test_succeeds_first_attempt(self):
        fn = MagicMock(return_value="ok")
        assert retry_link(fn) == "ok"
        assert fn.call_count == 1

    def test_succeeds_after_transient_failure(self):
        fn = MagicMock(side_effect=[ValueError("boom"), "ok"])
        result = retry_link(fn, max_retries=3, backoff=0)
        assert result == "ok"
        assert fn.call_count == 2

    def test_raises_after_max_retries(self):
        fn = MagicMock(side_effect=ValueError("fail"))
        with pytest.raises(ValueError, match="fail"):
            retry_link(fn, max_retries=2, backoff=0)
        assert fn.call_count == 2

    def test_emits_warning_on_exhaustion(self):
        fn = MagicMock(side_effect=RuntimeError("err"))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            with pytest.raises(RuntimeError):
                retry_link(fn, max_retries=2, backoff=0)
        assert len(w) == 1
        assert "exhausted 2 retries" in str(w[0].message)

    def test_logs_orphan_on_failure(self, tmp_path: Path):
        fn = MagicMock(side_effect=RuntimeError("timeout"))
        orphan_ctx = {
            "tracking_dir": str(tmp_path),
            "external_id": "ext-123",
            "todo_id": "todo-1",
            "service": "todoist",
        }
        with pytest.raises(RuntimeError):
            retry_link(fn, max_retries=1, backoff=0, orphan_context=orphan_ctx)

        orphan_file = tmp_path / ".orphaned-resources.yaml"
        assert orphan_file.exists()
        entries = yaml.safe_load(orphan_file.read_text())
        assert len(entries) == 1
        assert entries[0]["external_id"] == "ext-123"
        assert entries[0]["service"] == "todoist"
        assert "timeout" in entries[0]["error"]

    def test_no_orphan_log_without_context(self, tmp_path: Path):
        fn = MagicMock(side_effect=RuntimeError("err"))
        with pytest.raises(RuntimeError):
            retry_link(fn, max_retries=1, backoff=0)
        # No orphan file should be created anywhere
        assert not (tmp_path / ".orphaned-resources.yaml").exists()


# ---------------------------------------------------------------------------
# log_orphaned_resource
# ---------------------------------------------------------------------------


class TestLogOrphanedResource:
    def test_creates_new_file(self, tmp_path: Path):
        log_orphaned_resource(
            str(tmp_path),
            {"external_id": "abc", "service": "trello", "error": "oops"},
        )
        path = tmp_path / ".orphaned-resources.yaml"
        assert path.exists()
        entries = yaml.safe_load(path.read_text())
        assert len(entries) == 1
        assert entries[0]["external_id"] == "abc"
        assert "timestamp" in entries[0]

    def test_appends_to_existing_file(self, tmp_path: Path):
        log_orphaned_resource(str(tmp_path), {"external_id": "a", "error": "e1"})
        log_orphaned_resource(str(tmp_path), {"external_id": "b", "error": "e2"})
        entries = yaml.safe_load((tmp_path / ".orphaned-resources.yaml").read_text())
        assert len(entries) == 2
        assert entries[0]["external_id"] == "a"
        assert entries[1]["external_id"] == "b"

    def test_handles_corrupt_file_gracefully(self, tmp_path: Path):
        orphan_file = tmp_path / ".orphaned-resources.yaml"
        orphan_file.write_text("not: a: list: {{{")
        # Should not raise; overwrites with a fresh list
        log_orphaned_resource(str(tmp_path), {"external_id": "x", "error": "e"})
        entries = yaml.safe_load(orphan_file.read_text())
        assert len(entries) == 1

    def test_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c"
        log_orphaned_resource(str(nested), {"external_id": "z", "error": "missing"})
        assert (nested / ".orphaned-resources.yaml").exists()
