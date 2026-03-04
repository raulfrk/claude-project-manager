"""Read/write for ~/.claude/worktree.yaml."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

import yaml

from server.lib.models import WorktreeConfig

_DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "worktree.yaml"


def _config_path() -> Path:
    env = os.environ.get("WORKTREE_CONFIG", "")
    if env:
        return Path(env).expanduser()
    return _DEFAULT_CONFIG_PATH


def load() -> WorktreeConfig:
    """Load config, returning defaults if file doesn't exist."""
    path = _config_path()
    if not path.exists():
        return WorktreeConfig()
    with path.open() as f:
        data: dict[str, object] = yaml.safe_load(f) or {}
    return WorktreeConfig.from_dict(data)


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write content to path via a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        tmp.replace(path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def save(config: WorktreeConfig) -> None:
    """Write config to disk atomically."""
    content = yaml.dump(config.to_dict(), default_flow_style=False, sort_keys=False)
    _atomic_write(_config_path(), content)


def config_path() -> Path:
    """Expose config path for use in tools."""
    return _config_path()
