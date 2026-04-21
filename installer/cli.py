"""CLI argument parsing for the installer."""

from __future__ import annotations

import argparse

from installer import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the installer CLI."""
    parser = argparse.ArgumentParser(
        prog="claude-pm-installer",
        description="Install, reinstall, or uninstall claude-project-manager plugins.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Mutually exclusive mode flags
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--reinstall",
        action="store_true",
        help="Reinstall plugins from scratch.",
    )
    mode.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall plugins and remove configuration.",
    )

    parser.add_argument(
        "--full-cleanup",
        action="store_true",
        help="Remove all data and configuration. Implies --uninstall if used alone.",
    )

    parser.add_argument(
        "--plugins",
        nargs="+",
        metavar="PLUGIN",
        help="Limit operation to specific plugins (default: all).",
    )

    parser.add_argument(
        "--skip-wizard",
        action="store_true",
        help="Skip the interactive setup wizard during install.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )

    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Disable Textual TUI and use the plain Rich-based flow.",
    )

    parser.add_argument(
        "--branch",
        metavar="BRANCH",
        default=None,
        help="Git branch/ref to install from (e.g. --branch dev).",
    )

    parser.add_argument(
        "--local-marketplace",
        action="store_true",
        help=(
            "Clone the marketplace repo into ~/.cache/claude-project-manager/"
            "local-marketplace and register that path as the Claude Code "
            "marketplace source. Combines with --branch to select the branch "
            "checked out in the clone. Works with --reinstall and "
            "--skip-wizard."
        ),
    )

    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run the full migration chain (v1→v2→v3) for any project needing upgrade. Idempotent.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --migrate: print a dry-run report, no mutation.",
    )
    parser.add_argument(
        "--backup-retain",
        type=int,
        default=None,
        metavar="DAYS",
        help="Prune migration backups older than DAYS on next run (default: keep forever).",
    )
    parser.add_argument(
        "--strict-resync",
        action="store_true",
        help="Abort + revert local flatten on any remote resync failure (default: log + continue).",
    )

    return parser


def load_project_list() -> list[dict]:
    """Return projects to consider for migration as [{"name", "path"}, ...].

    Reads the proj plugin's project registry at <tracking_dir>/active-projects.yaml.
    Filters out archived projects. Returns empty list when registry is missing
    (fresh install, no projects yet).
    """
    import yaml
    from pathlib import Path

    config_path = Path.home() / ".claude" / "proj.yaml"
    if not config_path.exists():
        return []
    try:
        cfg = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return []
    tracking_dir = Path(cfg.get("tracking_dir") or "~/projects/tracking").expanduser()
    registry_path = tracking_dir / "active-projects.yaml"
    if not registry_path.exists():
        return []
    try:
        registry = yaml.safe_load(registry_path.read_text()) or {}
    except yaml.YAMLError:
        return []
    projects_map = registry.get("projects") or {}
    out: list[dict] = []
    for name, entry in projects_map.items():
        if entry.get("archived", False):
            continue
        path = entry.get("tracking_dir") or str(tracking_dir / name)
        out.append({"name": name, "path": path})
    return out
