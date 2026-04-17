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
        "--migrate",
        action="store_true",
        help="Run the full migration chain (v1→v2→v3) for any project needing upgrade.",
    )
    parser.add_argument(
        "--migrate-flat",
        action="store_true",
        help="Alias for --migrate (kept for backward-compat).",
    )
    parser.add_argument(
        "--migrate-sql-only",
        action="store_true",
        help="Run only the v2→v3 SQL-only migration (errors if any project is still v1).",
    )
    parser.add_argument(
        "--migrate-dry-run",
        action="store_true",
        help="Print a dry-run report of what migration would do, no mutation.",
    )
    parser.add_argument(
        "--migrate-flat-dry-run",
        action="store_true",
        help="Alias for --migrate-dry-run (kept for backward-compat).",
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
    """Read ~/.claude/proj.yaml and return the projects list (each with name + path)."""
    import yaml
    from pathlib import Path

    proj_yaml = Path.home() / ".claude" / "proj.yaml"
    if not proj_yaml.exists():
        return []
    data = yaml.safe_load(proj_yaml.read_text()) or {}
    return list(data.get("projects", []))
