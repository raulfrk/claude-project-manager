"""Tests for scripts/_gather_shared_version_state.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _gather_shared_version_state import (
    _extract_pyproject_version,
    _extract_transport_version,
)


def test_extract_pyproject_version_simple():
    """Standard version string extracted."""
    content = 'name = "claude-hook-transport"\nversion = "0.4.39"\n'
    assert _extract_pyproject_version(content) == "0.4.39"


def test_extract_pyproject_version_missing():
    """Returns None when version absent."""
    assert _extract_pyproject_version("name = 'foo'\n") is None


def test_extract_pyproject_version_single_quotes():
    """Single-quoted version string."""
    content = "version = '0.4.40'\n"
    assert _extract_pyproject_version(content) == "0.4.40"


def test_extract_transport_version_simple():
    """Finds claude-hook-transport block + version."""
    content = """[[package]]
name = "other-pkg"
version = "1.0.0"

[[package]]
name = "claude-hook-transport"
version = "0.4.40"
"""
    assert _extract_transport_version(content) == "0.4.40"


def test_extract_transport_version_dependency_array_false_positive():
    """Doesn't match `name = 'claude-hook-transport'` inside dependencies array."""
    content = """[[package]]
name = "consumer"
version = "1.0.0"
dependencies = [
    { name = "claude-hook-transport" }
]
"""
    assert _extract_transport_version(content) is None


def test_extract_transport_version_missing():
    """Returns None when no claude-hook-transport block."""
    content = '[[package]]\nname = "other"\nversion = "1.0"\n'
    assert _extract_transport_version(content) is None


def test_main_outputs_valid_json(monkeypatch, capsys):
    """Main outputs JSON w/ expected keys."""
    from _gather_shared_version_state import main

    # Mock subprocess.run to return canned data
    def fake_run(cmd, capture_output, text):
        class Result:
            returncode = 0
            stdout = ""

        if "diff" in cmd:
            Result.stdout = "plugins/_shared/foo.py\n"
        elif "show" in cmd and cmd[-1].endswith("pyproject.toml"):
            Result.stdout = 'version = "0.4.40"\n'
        else:
            # All lockfile lookups: stub claude-hook-transport block
            Result.stdout = (
                '[[package]]\nname = "claude-hook-transport"\nversion = "0.4.40"\n'
            )
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    state = json.loads(captured.out)
    assert "shared_py_staged" in state
    assert "head_version" in state
    assert "staged_version" in state
    assert "lockfiles" in state
