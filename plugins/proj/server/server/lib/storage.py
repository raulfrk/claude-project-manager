"""YAML I/O for proj plugin data files."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import yaml

from server.lib.models import (
    ProjConfig,
    ProjectIndex,
    ProjectMeta,
    Todo,
)

_DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "proj.yaml"


def _load_yaml(path: Path) -> dict[str, object]:
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
    data = _load_yaml(_index_path(cfg))
    return ProjectIndex.from_dict(data)


def save_index(cfg: ProjConfig, index: ProjectIndex) -> None:
    path = _index_path(cfg)
    _write_yaml(path, index.to_dict())


# ── Project metadata ──────────────────────────────────────────────────────────


def tracking_dir(cfg: ProjConfig, project_name: str) -> Path:
    return Path(cfg.tracking_dir).expanduser() / project_name


def meta_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "meta.yaml"


def load_meta(cfg: ProjConfig, project_name: str) -> ProjectMeta:
    path = meta_path(cfg, project_name)
    if not path.exists():
        msg = f"Project not found: {project_name}"
        raise FileNotFoundError(msg)
    data = _load_yaml(path)
    return ProjectMeta.from_dict(data)


def save_meta(cfg: ProjConfig, meta: ProjectMeta) -> None:
    path = meta_path(cfg, meta.name)
    meta.dates.last_updated = str(date.today())
    _write_yaml(path, meta.to_dict())


# ── Todos ─────────────────────────────────────────────────────────────────────


def todos_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "todos.yaml"


def load_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    data = _load_yaml(todos_path(cfg, project_name))
    todos_raw = data.get("todos", [])
    if not isinstance(todos_raw, list):
        return []
    return [Todo.from_dict(t) for t in todos_raw]  # type: ignore[arg-type]  # list[object] from YAML; items are dicts at runtime


def save_todos(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    path = todos_path(cfg, project_name)
    _write_yaml(path, {"todos": [t.to_dict() for t in todos]})


# ── Agents ────────────────────────────────────────────────────────────────────


def agents_path(cfg: ProjConfig, project_name: str) -> Path:
    """Return the path to agents.yaml for a project."""
    return tracking_dir(cfg, project_name) / "agents.yaml"


def load_agents(cfg: ProjConfig, project_name: str) -> dict[str, object]:
    """Load agents.yaml, returning empty dict if missing or empty."""
    data = _load_yaml(agents_path(cfg, project_name))
    if not data:
        return {}
    return data


def save_agents(cfg: ProjConfig, project_name: str, data: dict[str, object]) -> None:
    """Atomically write agents.yaml using the _write_yaml() helper."""
    path = agents_path(cfg, project_name)
    _write_yaml(path, data)


# ── Archive ────────────────────────────────────────────────────────────────────


def archive_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "archive.yaml"


def load_archived_todos(cfg: ProjConfig, project_name: str) -> list[Todo]:
    data = _load_yaml(archive_path(cfg, project_name))
    todos_raw = data.get("todos", [])
    if not isinstance(todos_raw, list):
        return []
    return [Todo.from_dict(t) for t in todos_raw]  # type: ignore[arg-type]  # list[object] from YAML; items are dicts at runtime


def save_archived_todos(cfg: ProjConfig, project_name: str, todos_to_add: list[Todo]) -> None:
    """Append todos to archive.yaml, creating it if needed."""
    existing = load_archived_todos(cfg, project_name)
    _write_yaml(archive_path(cfg, project_name), {"todos": [t.to_dict() for t in existing + todos_to_add]})


def archive_and_remove_todos(
    cfg: ProjConfig,
    project_name: str,
    remaining: list[Todo],
    to_archive: list[Todo],
) -> None:
    """Stage both archive append and active removal; commit archive-first to minimise data-loss window.

    Both writes are prepared as temp files before either is committed. Archive rename
    happens first so a failure between the two renames leaves the todo in the archive
    (recoverable duplication) rather than lost entirely.
    """
    existing = load_archived_todos(cfg, project_name)
    new_archive = existing + to_archive

    archive_p = archive_path(cfg, project_name)
    active_p = todos_path(cfg, project_name)
    archive_p.parent.mkdir(parents=True, exist_ok=True)

    fd_a, tmp_a_str = tempfile.mkstemp(dir=archive_p.parent, suffix=".tmp")
    tmp_a = Path(tmp_a_str)
    fd_t, tmp_t_str = tempfile.mkstemp(dir=active_p.parent, suffix=".tmp")
    tmp_t = Path(tmp_t_str)
    try:
        with os.fdopen(fd_a, "w") as f:
            yaml.dump(
                {"todos": [t.to_dict() for t in new_archive]},
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        with os.fdopen(fd_t, "w") as f:
            yaml.dump(
                {"todos": [t.to_dict() for t in remaining]},
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        tmp_a.replace(archive_p)
        tmp_t.replace(active_p)
    except Exception:
        tmp_a.unlink(missing_ok=True)
        tmp_t.unlink(missing_ok=True)
        raise


# ── Notes ─────────────────────────────────────────────────────────────────────


def notes_path(cfg: ProjConfig, project_name: str) -> Path:
    return tracking_dir(cfg, project_name) / "NOTES.md"


def append_note(cfg: ProjConfig, project_name: str, text: str) -> None:
    path = notes_path(cfg, project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    today = str(date.today())
    entry = f"\n## {today}\n\n{text.strip()}\n"
    with path.open("a") as f:
        f.write(entry)


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
    """Rename a todo's content directory from old_id to new_id. Returns True if renamed, False if not found."""
    old_path = todo_content_dir(cfg, project_name, old_id)
    new_path = todo_content_dir(cfg, project_name, new_id)
    if old_path.exists():
        old_path.rename(new_path)
        return True
    return False


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


def _write_yaml(path: Path, data: dict[str, object]) -> None:
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


def atomic_write_json(path: Path, data: dict[str, object]) -> None:
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
