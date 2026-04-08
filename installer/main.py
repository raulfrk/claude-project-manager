"""Entry point for the installer."""

from __future__ import annotations

import sys
from typing import IO

from rich.console import Console

from installer.cli import build_parser
from installer.detect import detect_existing, display_detection
from installer.errors import (
    InstallerError,
    UserCancelled,
    acquire_lock,
    check_prerequisites,
    check_root,
    release_lock,
)
from installer.app import InstallerApp
from installer.uninstall import run_uninstall
from installer.update import (
    compare_versions,
    display_version_diff,
    run_reinstall,
    run_update,
)
from installer.wizard import run_wizard

# Exit codes
EXIT_SUCCESS = 0
EXIT_CANCELLED = 1
EXIT_ERROR = 2


def _install(args) -> int:
    """Run the install flow."""
    print("Not implemented: install")
    return EXIT_SUCCESS


def _update(args) -> int:
    """Run the update flow."""
    console = Console()
    state = detect_existing()
    display_detection(state, console)

    if not state.installed_plugins:
        console.print("[yellow]No installed plugins found. Nothing to update.[/yellow]")
        return EXIT_SUCCESS

    # Show version diffs
    diffs = compare_versions(state)
    display_version_diff(diffs, console)

    if not diffs:
        return EXIT_SUCCESS

    # Determine which plugins to update
    plugins = args.plugins if args.plugins else list(diffs.keys())
    # Filter to only plugins that actually have diffs
    plugins = [p for p in plugins if p in diffs]

    if not plugins:
        console.print("[dim]No matching plugins need updating.[/dim]")
        return EXIT_SUCCESS

    console.print(f"\n[bold]Updating:[/bold] {', '.join(plugins)}")
    results = run_update(plugins, state, console)

    failed = [p for p, ok in results.items() if not ok]
    if failed:
        return EXIT_ERROR
    return EXIT_SUCCESS


def _reinstall(args) -> int:
    """Run the reinstall flow."""
    console = Console()
    state = detect_existing()
    display_detection(state, console)

    if not state.installed_plugins:
        console.print(
            "[yellow]No installed plugins found. Nothing to reinstall.[/yellow]"
        )
        return EXIT_SUCCESS

    # Determine which plugins to reinstall
    plugins = args.plugins if args.plugins else list(state.installed_plugins)

    console.print(f"\n[bold]Reinstalling:[/bold] {', '.join(plugins)}")
    results = run_reinstall(plugins, state, console)

    # Run wizard after reinstall if configs were reset
    if not args.skip_wizard:
        run_wizard(plugins, skip=False)

    failed = [p for p, ok in results.items() if not ok]
    if failed:
        return EXIT_ERROR
    return EXIT_SUCCESS


def _uninstall(args) -> int:
    """Run the uninstall flow."""
    console = Console()
    run_uninstall(full_cleanup=args.full_cleanup, console=console)
    return EXIT_SUCCESS


def main() -> int:
    """Parse arguments and dispatch to the appropriate flow."""
    lock_fh: IO | None = None

    try:
        parser = build_parser()
        args = parser.parse_args()

        # Safety checks
        check_root()
        check_prerequisites()

        # Prevent concurrent runs
        lock_fh = acquire_lock()

        # --full-cleanup without --uninstall implies --uninstall --full-cleanup
        if args.full_cleanup and not args.uninstall:
            args.uninstall = True

        # Determine mode for TUI routing
        if args.update:
            mode = "update"
        elif args.reinstall:
            mode = "reinstall"
        elif args.uninstall:
            mode = "uninstall"
        else:
            mode = "install"

        if args.no_tui:
            # Plain Rich-based flow
            if mode == "update":
                return _update(args)
            elif mode == "reinstall":
                return _reinstall(args)
            elif mode == "uninstall":
                return _uninstall(args)
            else:
                return _install(args)
        else:
            # Textual TUI flow
            app = InstallerApp(mode=mode, args=args)
            app.run()
            return EXIT_SUCCESS

    except KeyboardInterrupt:
        print("\nCancelled.")
        return EXIT_CANCELLED
    except UserCancelled as exc:
        print(str(exc))
        return exc.exit_code
    except InstallerError as exc:
        print(f"Error: {exc}")
        return exc.exit_code
    finally:
        release_lock(lock_fh)


if __name__ == "__main__":
    sys.exit(main())
