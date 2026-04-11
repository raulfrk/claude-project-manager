#!/usr/bin/env python3
"""Pre-commit hook: fail if plugins/_shared/*.py staged but version not bumped."""

import re
import subprocess
import sys


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


def main() -> int:
    staged = get_staged_files()
    shared_py_staged = [
        f for f in staged if f.startswith("plugins/_shared/") and f.endswith(".py")
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
