#!/usr/bin/env python3
"""Gather _shared version state for conftest. Outputs JSON to stdout.

Replaces the assertion logic of scripts/check_shared_version.py — assertion
moves to policies/shared_version_cascade.rego. This script only collects state.

Usage:
    python scripts/_gather_shared_version_state.py | conftest test --policy policies/ -
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

LOCKFILES = [
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
]


def _git_show(ref: str, path: str) -> str | None:
    """`git show <ref>:<path>` — returns content or None if missing.

    `ref` may be empty string for the staged index (i.e. `git show :<path>`).
    """
    r = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _extract_pyproject_version(content: str) -> str | None:
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return m.group(1) if m else None


def _extract_transport_version(lockfile_content: str) -> str | None:
    """Find the claude-hook-transport [[package]] block + extract version."""
    for block in lockfile_content.split("[[package]]"):
        if not re.search(r'^name\s*=\s*"claude-hook-transport"', block, re.MULTILINE):
            continue
        m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', block, re.MULTILINE)
        if m:
            return m.group(1)
    return None


def main() -> int:
    staged_files = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    shared_py_staged = [
        f
        for f in staged_files
        if f.startswith("plugins/_shared/")
        and f.endswith(".py")
        and not f.startswith("plugins/_shared/tests/")
    ]

    head_pyproject = _git_show("HEAD", "plugins/_shared/pyproject.toml")
    staged_pyproject = _git_show("", "plugins/_shared/pyproject.toml")

    state: dict = {
        "shared_py_staged": shared_py_staged,
        "head_version": _extract_pyproject_version(head_pyproject)
        if head_pyproject
        else None,
        "staged_version": _extract_pyproject_version(staged_pyproject)
        if staged_pyproject
        else None,
        "lockfiles": {},
    }

    for path in LOCKFILES:
        content = _git_show("", path)
        state["lockfiles"][path] = (
            _extract_transport_version(content) if content else None
        )

    json.dump(state, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
