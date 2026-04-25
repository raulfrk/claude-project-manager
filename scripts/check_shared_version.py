#!/usr/bin/env python3
# See check_shared_version.md for the validate-vs-auto-regen evaluation rubric.
"""Pre-commit hook: fail if plugins/_shared/*.py staged but version not bumped."""

import re
import subprocess
import sys

LOCKFILES: list[str] = [
    "uv.lock",  # repo root (installer pyproject)
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


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
    )
    return result.stdout.splitlines()


def get_version_from_git(ref: str) -> str | None:
    """Get version from pyproject.toml at given git ref (e.g. ':' for staged, 'HEAD:' for HEAD)."""
    result = subprocess.run(
        ["git", "show", f"{ref}plugins/_shared/pyproject.toml"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', result.stdout, re.MULTILINE)
    return m.group(1) if m else None


def _extract_transport_version(content: str) -> str | None:
    """Return the claude-hook-transport version pinned in a uv.lock content string.

    Lockfiles are TOML-ish; claude-hook-transport appears as a [[package]] block with
    name = "claude-hook-transport" and version = "X.Y.Z". The version and name lines
    can appear in either order within the block, so parse block-by-block.
    """
    blocks = content.split("[[package]]")
    for block in blocks:
        # Match only a top-level TOML `name` key at line start — avoids false
        # positives against `{ name = "claude-hook-transport" }` inside the
        # `dependencies` array of OTHER packages.
        if not re.search(r'^name\s*=\s*"claude-hook-transport"', block, re.MULTILINE):
            continue
        m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', block, re.MULTILINE)
        if m:
            return m.group(1)
    return None


def _check_lockfiles_pin_new_version(
    new_version: str,
) -> list[tuple[str, str, str | None]]:
    """For each declared lockfile, read its staged content via `git show :<path>` and
    verify it pins `claude-hook-transport == new_version`.

    Returns a list of (path, expected, actual) tuples for lockfiles that drift. `actual`
    is None when the lockfile is missing from the staged index or does not reference
    claude-hook-transport.
    """
    drift: list[tuple[str, str, str | None]] = []
    for path in LOCKFILES:
        result = subprocess.run(
            ["git", "show", f":{path}"], capture_output=True, text=True
        )
        if result.returncode != 0:
            drift.append((path, new_version, None))
            continue
        actual = _extract_transport_version(result.stdout)
        if actual is None:
            drift.append((path, new_version, None))
            continue
        if actual != new_version:
            drift.append((path, new_version, actual))
    return drift


def main() -> int:
    staged = get_staged_files()
    # Exclude plugins/_shared/tests/ — test-only changes don't alter the
    # claude-hook-transport package contents, so they shouldn't require
    # a version bump + lockfile regen.
    shared_py_staged = [
        f
        for f in staged
        if f.startswith("plugins/_shared/")
        and f.endswith(".py")
        and not f.startswith("plugins/_shared/tests/")
    ]
    if not shared_py_staged:
        return 0  # no _shared .py files staged — nothing to check

    staged_version = get_version_from_git(":")  # staged version
    head_version = get_version_from_git("HEAD:")  # HEAD version

    if head_version is None:
        # No HEAD version (initial commit) — skip check
        return 0

    if staged_version is None:
        print(
            "ERROR: plugins/_shared/pyproject.toml not found in staged files. Cannot verify version bump."
        )
        return 1

    if staged_version == head_version:
        print(
            f"ERROR: plugins/_shared/*.py staged but version not bumped (still {staged_version})."
        )
        print("Bump version in plugins/_shared/pyproject.toml before committing.")
        return 1

    # Version bumped — verify every declared uv.lock pins the new version.
    drift = _check_lockfiles_pin_new_version(staged_version)
    if drift:
        print(
            f"ERROR: plugins/_shared version bumped to {staged_version}, but the following "
            "uv.lock files do not reference the new claude-hook-transport version:"
        )
        for path, expected, actual in drift:
            actual_display = (
                actual if actual is not None else "(missing or unparseable)"
            )
            print(f"  {path}: expected {expected}, got {actual_display}")
        print(
            "Run `just sync` at repo root to regenerate all uv.lock files, then "
            "`git add <paths>` and commit again."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
