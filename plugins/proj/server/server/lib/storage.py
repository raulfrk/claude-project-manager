"""YAML I/O for proj plugin data files."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from server.lib import schema_version, sql_archive, sql_decisions, sql_meta, sql_todos
from server.lib.migration import _ensure_migrated
from server.lib.models import (
    Decision,
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
    sql_meta.save_meta(cfg, meta)


# ── Todos ─────────────────────────────────────────────────────────────────────


def todos_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "todos.yaml"


def load_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    schema_version.require_current(cfg, project_name)
    _ensure_migrated(cfg, project_name)
    return sql_todos.load_todos(cfg, project_name)


def save_todos(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    schema_version.require_current(cfg, project_name)
    sql_todos.save_todos(cfg, project_name, todos)


# ── Archive ────────────────────────────────────────────────────────────────────


def archive_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "archive.yaml"


def load_archived_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    schema_version.require_current(cfg, project_name)
    # No _ensure_migrated — sql_todos.load_archived_todos handles the
    # archive.yaml.bak disaster-recovery fallback when data.db is missing.
    return sql_todos.load_archived_todos(cfg, project_name)


def save_archived_todos(cfg: ProjConfig, project_name: str, todos_to_add: list[Todo]) -> None:
    """Append todos to archive, creating it if needed."""
    schema_version.require_current(cfg, project_name)
    sql_todos.save_archived_todos_append(cfg, project_name, todos_to_add)


def replace_archived_todos(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    """Replace all archived todos for a project atomically (DELETE + INSERT)."""
    sql_todos.replace_archived_todos(cfg, project_name, todos)


def archive_and_remove_todos(
    cfg: ProjConfig,
    project_name: str,
    remaining: list[Todo],
    to_archive: list[Todo],
) -> None:
    """Move todos to archive atomically."""
    sql_archive.archive_and_remove_todos(cfg, project_name, remaining, to_archive)


def migrate_done_to_archive(cfg: ProjConfig, project_name: str) -> dict[str, int]:
    """Move terminal-status todos to archive based on tree rules."""
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


def _decision_to_dict(d: Decision) -> dict[str, JsonValue]:
    """Convert a Decision dataclass to the legacy dict format used by tools/tests."""
    return {
        "timestamp": d.timestamp,
        "decision": d.text,
        "context": "",
        "todo_id": d.todo_id or "",
        "tags": d.tags,
    }


def _dict_to_decision(entry: dict[str, JsonValue]) -> Decision:
    """Convert a legacy dict entry to a Decision dataclass.

    Preserves raw timestamp strings (including empty/invalid ones) so that
    context_injection can skip entries with bad timestamps.
    """
    tags_raw = entry.get("tags", [])
    tags: list[str] = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []
    # Accept either 'text' (new) or 'decision' (legacy) as the decision text
    text = str(entry.get("text") or entry.get("decision") or "")
    # Preserve the raw timestamp as-is (even if empty/invalid) so context_injection
    # can skip entries with bad timestamps. Only None becomes empty string.
    raw_ts = entry.get("timestamp")
    timestamp = str(raw_ts) if raw_ts is not None else ""
    return Decision(
        timestamp=timestamp,
        text=text,
        todo_id=str(entry["todo_id"]) if entry.get("todo_id") else None,
        tags=tags,
    )


def load_decisions(cfg: ProjConfig, project_name: str) -> list[dict[str, JsonValue]]:
    """Read decisions for project from SQLite — returns legacy dict format."""
    decisions = sql_decisions.load_decisions(cfg, project_name)
    return [_decision_to_dict(d) for d in decisions]


def append_decision(cfg: ProjConfig, project_name: str, entry: dict[str, JsonValue]) -> None:
    """Append a single decision entry to SQLite."""
    sql_decisions.append_decision(cfg, project_name, _dict_to_decision(entry))


def replace_decisions(
    cfg: ProjConfig, project_name: str, entries: list[dict[str, JsonValue]]
) -> None:
    """Replace all decisions for a project atomically (DELETE + INSERT)."""
    sql_decisions.save_decisions(cfg, project_name, [_dict_to_decision(e) for e in entries])


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


def append_note(
    cfg: ProjConfig,
    project_name: str,
    text: str,
    heading: str | None = None,
    op: str = "note",
    _ts: str | None = None,
) -> None:
    path = notes_path(cfg, project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if heading is not None:
        ts = _ts if _ts is not None else datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## [{ts}] {op} | {heading}\n\n{text.strip()}\n"
    else:
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
