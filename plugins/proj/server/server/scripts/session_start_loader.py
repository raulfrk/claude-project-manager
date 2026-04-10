"""Claude Code SessionStart hook: auto-load a tracked project based on cwd.

Standalone script intentionally free of FastMCP / server-package imports so
cold-start latency stays low. The detection logic mirrors
``ctx_detect_project_name`` in ``plugins/proj/server/server/tools/context.py``
(canonical source). If that MCP tool's semantics evolve, update this script too;
grep for ``session_start_loader`` when touching ``ctx_detect_project_name``.

CLI::

    python -m server.scripts.session_start_loader --cwd "$CLAUDE_PROJECT_DIR"

On match, prints exactly one line to stdout::

    proj_load_session("<project_name>")

On no match or any error, exits silently with code 0 so the session is never
failed by this hook. Orphaned or corrupt per-project ``meta.yaml`` files are
counted and surfaced as a single stderr warning at end-of-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TRACKING_DIR = Path.home() / "projects" / "tracking"
PROJ_CONFIG_PATH = Path.home() / ".claude" / "proj.yaml"
WARNING_PREFIX = "[session-start-loader] warning:"


def _resolve_tracking_dir(override: Path | None) -> Path:
    """Return the effective tracking dir, honoring override > proj.yaml > default."""
    if override is not None:
        return override.expanduser()
    try:
        raw = PROJ_CONFIG_PATH.read_text()
        cfg = yaml.safe_load(raw)
        if isinstance(cfg, dict):
            td = cfg.get("tracking_dir")
            if isinstance(td, str) and td:
                return Path(td).expanduser()
    except Exception:  # noqa: S110 — never fail the session for config parse errors
        pass
    return DEFAULT_TRACKING_DIR


def _load_yaml(path: Path) -> dict[str, Any] | None:
    """Safe YAML load. Returns None on any failure (missing, corrupt, non-dict)."""
    try:
        data = yaml.safe_load(path.read_text())
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


def _emit_warning(unreadable: int) -> None:
    if unreadable > 0:
        print(
            f"{WARNING_PREFIX} {unreadable} project(s) had unreadable meta.yaml",
            file=sys.stderr,
        )


def detect_project_for_cwd(
    cwd: str,
    tracking_dir: Path | None = None,
    index_path: Path | None = None,
) -> str | None:
    """Return the project name that claims ``cwd``, or ``None``.

    Detection rules (mirror ``ctx_detect_project_name``):
    - Normalize ``cwd`` and each repo path via ``Path.expanduser().resolve()``.
    - A project claims cwd if ``cwd.is_relative_to(repo_resolved)`` for any of
      its registered repos (handles exact match and walk-up subdirectories).
    - Archived projects are skipped.
    - Tie-breaker: first non-archived project in index iteration order wins.
    """
    if not cwd:
        return None

    td = _resolve_tracking_dir(tracking_dir)
    idx_path = index_path.expanduser() if index_path is not None else td / "active-projects.yaml"

    index = _load_yaml(idx_path)
    if index is None:
        return None

    projects_raw = index.get("projects")
    if not isinstance(projects_raw, dict):
        return None

    try:
        cwd_resolved = Path(cwd).expanduser().resolve()
    except Exception:
        return None

    unreadable = 0
    match: str | None = None

    # Iterate in index iteration order for deterministic tie-breaking.
    for name, entry in projects_raw.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        if entry.get("archived"):
            continue

        meta_path = td / name / "meta.yaml"
        if not meta_path.exists():
            unreadable += 1
            continue
        meta = _load_yaml(meta_path)
        if meta is None:
            unreadable += 1
            continue

        repos = meta.get("repos")
        if not isinstance(repos, list):
            continue

        for repo in repos:
            raw_path: Any = repo.get("path") if isinstance(repo, dict) else repo
            if not isinstance(raw_path, str) or not raw_path:
                continue
            try:
                repo_resolved = Path(raw_path).expanduser().resolve()
            except Exception:  # noqa: S112 — skip unresolvable repo paths silently
                continue
            try:
                if cwd_resolved.is_relative_to(repo_resolved):
                    match = name
                    break
            except Exception:  # noqa: S112 — skip on comparison failure
                continue

        if match is not None:
            break

    _emit_warning(unreadable)
    return match


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SessionStart loader for tracked claude-project-manager projects.",
    )
    parser.add_argument("--cwd", default="", help="Session cwd (typically $CLAUDE_PROJECT_DIR).")
    parser.add_argument("--tracking-dir", default=None, help="Override tracking dir.")
    parser.add_argument("--index-path", default=None, help="Override full index file path.")
    args = parser.parse_args(argv)

    try:
        name = detect_project_for_cwd(
            args.cwd,
            tracking_dir=Path(args.tracking_dir) if args.tracking_dir else None,
            index_path=Path(args.index_path) if args.index_path else None,
        )
    except Exception:
        return 0

    if name:
        # Escape backslashes then double-quotes so the activation line is safe
        # even for project names containing those characters.
        safe = name.replace("\\", "\\\\").replace('"', '\\"')
        print(f'proj_load_session("{safe}")')
    return 0


if __name__ == "__main__":
    sys.exit(main())
