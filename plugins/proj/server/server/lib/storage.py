"""YAML I/O for proj plugin data files."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from server.lib import sql_archive, sql_decisions, sql_meta, sql_todos
from server.lib.migration import _ensure_migrated
from server.lib.models import (
    JsonValue,
    ProjConfig,
    ProjectIndex,
    ProjectMeta,
    Todo,
)

_DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "proj.yaml"


def _load_yaml(path: Path) -> dict[str, JsonValue]:
    """Load a YAML file, returning an empty dict if the file doesn't exist or is corrupt."""
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except (FileNotFoundError, yaml.YAMLError):
        return {}


# ── Config ────────────────────────────────────────────────────────────────────


def config_path() -> Path:
    env = os.environ.get("PROJ_CONFIG", "")
    return Path(env).expanduser() if env else _DEFAULT_CONFIG_PATH


def load_config() -> ProjConfig:
    data = _load_yaml(config_path())
    return ProjConfig.from_dict(data)


def save_config(cfg: ProjConfig) -> None:
    path = config_path()
    _write_yaml(path, cfg.to_dict())


def config_exists() -> bool:
    return config_path().exists()


# ── Project index ─────────────────────────────────────────────────────────────


def _index_path(cfg: ProjConfig) -> Path:
    return Path(cfg.tracking_dir).expanduser() / "active-projects.yaml"


def load_index(cfg: ProjConfig) -> ProjectIndex:
    return sql_meta.load_index(cfg)


def save_index(cfg: ProjConfig, index: ProjectIndex) -> None:
    sql_meta.save_index(cfg, index)


# ── Project metadata ──────────────────────────────────────────────────────────


def tracking_dir(cfg: ProjConfig, project_name: str) -> Path:
    return Path(cfg.tracking_dir).expanduser() / project_name


def meta_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "meta.yaml"


def load_meta(cfg: ProjConfig, project_name: str) -> ProjectMeta:
    _ensure_migrated(cfg, project_name)
    return sql_meta.load_meta(cfg, project_name)


def save_meta(cfg: ProjConfig, meta: ProjectMeta) -> None:
    _ensure_migrated(cfg, meta.name)
    sql_meta.save_meta(cfg, meta)


# ── Todos ─────────────────────────────────────────────────────────────────────


def todos_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "todos.yaml"


def load_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    _ensure_migrated(cfg, project_name)
    return sql_todos.load_todos(cfg, project_name)


def save_todos(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    _ensure_migrated(cfg, project_name)
    sql_todos.save_todos(cfg, project_name, todos)


# ── Archive ────────────────────────────────────────────────────────────────────


def archive_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "archive.yaml"


def load_archived_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    _ensure_migrated(cfg, project_name)
    return sql_todos.load_archived_todos(cfg, project_name)


def save_archived_todos(cfg: ProjConfig, project_name: str, todos_to_add: list[Todo]) -> None:
    """Append todos to archive, creating it if needed."""
    _ensure_migrated(cfg, project_name)
    sql_todos.save_archived_todos_append(cfg, project_name, todos_to_add)


def archive_and_remove_todos(
    cfg: ProjConfig,
    project_name: str,
    remaining: list[Todo],
    to_archive: list[Todo],
) -> None:
    """Move todos to archive atomically."""
    _ensure_migrated(cfg, project_name)
    sql_archive.archive_and_remove_todos(cfg, project_name, remaining, to_archive)


def migrate_done_to_archive(cfg: ProjConfig, project_name: str) -> dict[str, int]:
    """Move terminal-status todos to archive based on tree rules."""
    _ensure_migrated(cfg, project_name)
    return sql_archive.migrate_done_to_archive(cfg, project_name)


# ── Sessions / Decisions ──────────────────────────────────────────────────


def sessions_dir(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "sessions"


def decisions_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "decisions.yaml"


def _load_yaml_list(path: Path) -> list[dict[str, JsonValue]]:
    """Load a YAML file that contains a top-level list, returning [] if missing or corrupt."""
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
            if not isinstance(data, list):
                return []
            return data
    except (FileNotFoundError, yaml.YAMLError):
        return []


def _write_yaml_list(path: Path, data: list[dict[str, JsonValue]]) -> None:
    """Atomically write a YAML file containing a top-level list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def load_decisions(cfg: ProjConfig, project_name: str) -> list[dict[str, JsonValue]]:
    """Read decisions for project from SQLite."""
    _ensure_migrated(cfg, project_name)
    return sql_decisions.load_decisions(cfg, project_name)  # type: ignore[return-value]


def append_decision(cfg: ProjConfig, project_name: str, entry: dict[str, JsonValue]) -> None:
    """Append a single decision entry to SQLite."""
    _ensure_migrated(cfg, project_name)
    sql_decisions.append_decision(cfg, project_name, entry)  # type: ignore[arg-type]


def build_decision_entry(
    decision: str,
    context: str = "",
    todo_id: str = "",
    tags: list[str] | None = None,
) -> dict[str, JsonValue]:
    """Build a decision entry dict with a UTC timestamp."""
    return {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "decision": decision,
        "context": context,
        "todo_id": todo_id,
        "tags": tags or [],
    }


# ── Notes ─────────────────────────────────────────────────────────────────────


def notes_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "NOTES.md"


def append_note(cfg: ProjConfig, project_name: str, text: str) -> None:
    path = notes_path(cfg, project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    today = str(date.today())
    entry = f"\n## {today}\n\n{text.strip()}\n"
    existing = path.read_text() if path.exists() else ""
    _atomic_write_text(path, existing + entry)


def read_notes(cfg: ProjConfig, project_name: str, max_chars: int = 2000) -> str:
    path = notes_path(cfg, project_name)
    if not path.exists():
        return ""
    text = path.read_text()
    return text[-max_chars:] if len(text) > max_chars else text


# ── Per-todo content ──────────────────────────────────────────────────────────


def todo_content_dir(cfg: ProjConfig, project_name: str, todo_id: str) -> Path:
    return tracking_dir(cfg, project_name) / "todos" / todo_id


def rename_todo_dir(cfg: ProjConfig, project_name: str, old_id: str, new_id: str) -> bool:
    """Rename a todo's content directory from old_id to new_id.

    Returns True if renamed, False if not found.
    """
    old_path = todo_content_dir(cfg, project_name, old_id)
    new_path = todo_content_dir(cfg, project_name, new_id)
    if not old_path.exists():
        return False
    if new_path.exists():
        raise FileExistsError(f"Cannot rename todo dir: target '{new_path}' already exists")
    old_path.rename(new_path)
    return True


def requirements_path(cfg: ProjConfig, project_name: str, todo_id: str) -> Path:
    return todo_content_dir(cfg, project_name, todo_id) / "requirements.md"


def research_path(cfg: ProjConfig, project_name: str, todo_id: str) -> Path:
    return todo_content_dir(cfg, project_name, todo_id) / "research.md"


def write_requirements(cfg: ProjConfig, project_name: str, todo_id: str, content: str) -> None:
    path = requirements_path(cfg, project_name, todo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def read_requirements(cfg: ProjConfig, project_name: str, todo_id: str) -> str | None:
    path = requirements_path(cfg, project_name, todo_id)
    return path.read_text() if path.exists() else None


def write_research(cfg: ProjConfig, project_name: str, todo_id: str, content: str) -> None:
    path = research_path(cfg, project_name, todo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def read_research(cfg: ProjConfig, project_name: str, todo_id: str) -> str | None:
    path = research_path(cfg, project_name, todo_id)
    return path.read_text() if path.exists() else None


# ── CLAUDE.md ─────────────────────────────────────────────────────────────────


def claudemd_path(repo_path: str) -> Path:
    return Path(repo_path) / "CLAUDE.md"


def write_claudemd(repo_path: str, content: str) -> None:
    path = claudemd_path(repo_path)
    path.write_text(content)


def read_claudemd(repo_path: str) -> str | None:
    path = claudemd_path(repo_path)
    return path.read_text() if path.exists() else None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _write_yaml(path: Path, data: dict[str, JsonValue]) -> None:
    """Atomically write a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically write raw text to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, data: dict[str, JsonValue]) -> None:
    """Atomically write a JSON file via a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2) + "\n"
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
