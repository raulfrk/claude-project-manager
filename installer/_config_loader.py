"""Shared helpers for loading existing YAML config during installer wizard.

Both the Rich CLI path (installer/wizard.py) and the Textual TUI path
(installer/screens/*.py) use this module to read ~/.claude/proj.yaml,
~/.claude/worktree.yaml, ~/.claude/todoist.yaml, ~/.claude/trello.yaml,
and ~/.claude/jira.yaml and surface existing values as wizard defaults.

Contract:
- load_existing_yaml(path) returns {} on missing or empty files, raises
  ConfigLoadError on parse errors, permission denied, >1MB files, or
  symlinks/non-regular files pointing outside ~/.claude/.
- get_nested(d, dotted_key, default) walks a nested dict by dotted path.
  Explicit-None contract: `key: null` in yaml is treated as missing and
  falls through to default. Rationale: users may `null` a value to
  intentionally clear it and re-prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Soft ceiling on yaml file size. Protects against accidental redirect of a
# large log file into ~/.claude/proj.yaml and against malicious symlinks
# pointing at /dev/zero or multi-GB files.
_MAX_YAML_BYTES = 1_048_576  # 1 MB


class ConfigLoadError(Exception):
    """Raised when an existing yaml config file cannot be parsed."""

    def __init__(self, path: Path, original: Exception) -> None:
        super().__init__(f"Failed to load {path}: {original}")
        self.path = path
        self.original = original


def _verify_under_claude_home(path: Path) -> None:
    """Verify resolved path stays under ~/.claude/ (or is given as an absolute
    path inside a tmp_path used by tests).

    A symlink whose target escapes ~/.claude/ is rejected via ConfigLoadError.
    Absolute paths passed in directly (e.g. pytest tmp_path) skip this check
    if they do not sit under ~/.claude/ — tests legitimately pass such paths.
    """
    try:
        real = path.resolve(strict=True)
    except FileNotFoundError:
        # Caller already handled missing-file case; should not reach here.
        return
    home_claude = (Path.home() / ".claude").resolve()
    # Only enforce the containment check when the caller asked for a path
    # inside ~/.claude/. This keeps tmp_path-based tests working without a
    # dedicated opt-out while still catching symlinks that redirect a
    # ~/.claude/*.yaml request at a path elsewhere on disk.
    try:
        asked = path.absolute()
    except OSError:
        return
    try:
        asked.relative_to(home_claude)
    except ValueError:
        return  # path was never under ~/.claude/; don't enforce
    try:
        real.relative_to(home_claude)
    except ValueError as exc:
        raise ConfigLoadError(
            path,
            OSError(f"symlink escapes ~/.claude/: {path} -> {real}"),
        ) from exc


def load_existing_yaml(path: Path) -> dict[str, Any]:
    """Return the parsed yaml dict at path, or {} if missing/empty.

    Raises ConfigLoadError on:
    - yaml parse errors
    - permission denied (chmod 000, directory lacks x, etc.)
    - files larger than 1 MB
    - non-regular files (directories, devices, pipes)
    - symlinks whose target escapes ~/.claude/ (when path itself is under it)

    A file that contains only whitespace, a null document, or a non-dict
    top-level value is treated as empty and returns {}.
    """
    # Use stat() instead of exists() because pathlib.Path.exists() on Py3.12+
    # swallows PermissionError via _ignore_error and returns False, which
    # would overwrite a chmod-000 file with a fresh-install default. os.access
    # has the same masking problem. stat() is the only reliable signal.
    try:
        st = path.stat()
    except FileNotFoundError:
        return {}
    except PermissionError as exc:
        raise ConfigLoadError(path, exc) from exc

    if st.st_size > _MAX_YAML_BYTES:
        raise ConfigLoadError(
            path,
            OSError(
                f"config file too large: {st.st_size} bytes (max {_MAX_YAML_BYTES})"
            ),
        )

    if not path.is_file():
        raise ConfigLoadError(
            path,
            OSError(f"not a regular file: {path}"),
        )

    _verify_under_claude_home(path)

    try:
        raw = path.read_text(encoding="utf-8-sig")
    except PermissionError as exc:
        raise ConfigLoadError(path, exc) from exc
    except OSError as exc:
        raise ConfigLoadError(path, exc) from exc
    if not raw.strip():
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(path, exc) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def get_nested(d: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Walk dict d by dotted_key, returning default on any miss.

    Returns default if:
    - any intermediate segment is missing
    - any intermediate value is None or not a dict
    - the final value is None (explicit-None contract: `key: null` in yaml
      is treated as missing and falls through to default)

    Never raises; always returns either the found value or the default.
    """
    if not dotted_key:
        return default
    current: Any = d
    for segment in dotted_key.split("."):
        if not isinstance(current, dict):
            return default
        if segment not in current:
            return default
        current = current[segment]
        if current is None:
            return default
    return current
