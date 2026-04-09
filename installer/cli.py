"""CLI argument parsing for the installer."""

from __future__ import annotations

import argparse

from installer import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the installer CLI."""
    parser = argparse.ArgumentParser(
        prog="claude-pm-installer",
        description="Install, update, or uninstall claude-project-manager plugins.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Mutually exclusive mode flags
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--update",
        action="store_true",
        help="Update installed plugins to the latest version.",
    )
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

    return parser
