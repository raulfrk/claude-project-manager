"""Entry point for the installer."""

from __future__ import annotations

import sys
from typing import IO

from rich.console import Console

from rich.prompt import Confirm

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
from installer.plugin_cli import (
    add_marketplace,
    check_marketplace_registered,
    get_available_plugins,
    get_installed_plugins,
    install_plugin,
    remove_marketplace,
    uninstall_plugin,
    update_plugin,
)
from installer.uninstall import cleanup_config_files
from installer.tui import load_plugins, select_plugins
from installer.update import (
    compare_versions,
    display_version_diff,
)
from installer.wizard import run_wizard

# Exit codes
EXIT_SUCCESS = 0
EXIT_CANCELLED = 1
EXIT_ERROR = 2


def _install(args) -> int:
    """Run the install flow."""
    console = Console()

    # 1. Determine plugin list
    if args.plugins:
        selected = list(args.plugins)
    else:
        plugins = load_plugins(branch=getattr(args, "branch", None))
        selected = select_plugins(plugins, console=console)

    if not selected:
        console.print("[dim]No plugins selected. Nothing to install.[/dim]")
        return EXIT_SUCCESS

    # 2. Run the setup wizard
    run_wizard(selected, skip=args.skip_wizard)

    # 3. Ensure marketplace is registered (with optional branch)
    branch = getattr(args, "branch", None)
    with console.status("[bold]Checking marketplace registration..."):
        if not check_marketplace_registered():
            branch_msg = f" (branch: {branch})" if branch else ""
            console.print(f"Marketplace not registered. Adding...{branch_msg}")
            add_marketplace(branch=branch)
            console.print("[green]Marketplace registered.[/green]")
        elif branch:
            console.print(f"Re-adding marketplace for branch: {branch}")
            remove_marketplace()
            add_marketplace(branch=branch)
            console.print(f"[green]Marketplace updated to branch {branch}.[/green]")
        else:
            console.print("[dim]Marketplace already registered.[/dim]")

    # 4. Check already-installed plugins and build name→ID map
    installed_ids = get_installed_plugins()
    available_ids = get_available_plugins()
    name_to_id: dict[str, str] = {}
    for pid in available_ids + installed_ids:
        name_to_id.setdefault(pid.split("@")[0], pid)
    installed_names = {pid.split("@")[0] for pid in installed_ids}

    # 5. Install each plugin
    results: dict[str, str] = {}  # name -> "installed" | "failed" | "skipped"
    for name in selected:
        plugin_id = name_to_id.get(name)
        if plugin_id is None:
            console.print(f"  [red]✗[/red] {name} not found in marketplace")
            results[name] = "failed"
            continue

        if name in installed_names:
            if not Confirm.ask(
                f"Plugin [bold]{name}[/bold] already installed. Reinstall?",
                default=False,
                console=console,
            ):
                results[name] = "skipped"
                continue
            # Uninstall first for reinstall
            with console.status(f"[bold]Uninstalling {name}...[/bold]"):
                uninstall_plugin(plugin_id)

        while True:
            try:
                with console.status(f"[bold]Installing {name}...[/bold]"):
                    install_plugin(plugin_id)
                console.print(f"  [green]✓[/green] {name} installed")
                results[name] = "installed"
                break
            except InstallerError as exc:
                console.print(f"  [red]✗[/red] {name} failed: {exc}")
                if Confirm.ask("Retry this plugin?", default=False, console=console):
                    continue
                results[name] = "failed"
                break

    # 6. Summary
    n_installed = sum(1 for v in results.values() if v == "installed")
    n_failed = sum(1 for v in results.values() if v == "failed")
    n_skipped = sum(1 for v in results.values() if v == "skipped")
    console.print(
        f"\n[bold]Summary:[/bold] {n_installed} installed, "
        f"{n_failed} failed, {n_skipped} skipped"
    )

    if n_installed > 0:
        console.print(
            "\n[bold cyan]Restart Claude Code for plugins to take effect.[/bold cyan]"
        )

    return EXIT_ERROR if n_failed > 0 else EXIT_SUCCESS


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
    results: dict[str, bool] = {}
    for name in plugins:
        try:
            console.print(f"  Updating [cyan]{name}[/cyan]...")
            update_plugin(name)
            console.print(f"  [green]✓[/green] {name} updated")
            results[name] = True
        except InstallerError as exc:
            console.print(f"  [red]✗[/red] {name}: {exc}")
            if Confirm.ask("  Retry?", default=False):
                try:
                    update_plugin(name)
                    console.print(f"  [green]✓[/green] {name} updated")
                    results[name] = True
                except InstallerError as retry_exc:
                    console.print(f"  [red]✗[/red] {name}: {retry_exc}")
                    results[name] = False
            else:
                results[name] = False

    succeeded = sum(1 for ok in results.values() if ok)
    failed_count = sum(1 for ok in results.values() if not ok)
    console.print(
        f"\n[bold]Summary:[/bold] {succeeded} succeeded, {failed_count} failed"
    )

    if failed_count:
        return EXIT_ERROR
    return EXIT_SUCCESS


def _reinstall(args) -> int:
    """Run the reinstall flow."""
    console = Console()
    state = detect_existing()
    display_detection(state, console)

    installed = get_installed_plugins()
    if not installed:
        console.print(
            "[yellow]No installed plugins found. Nothing to reinstall.[/yellow]"
        )
        return EXIT_SUCCESS

    # Determine which plugins to reinstall
    plugins = args.plugins if args.plugins else list(installed)

    console.print(f"\n[bold]Reinstalling:[/bold] {', '.join(plugins)}")
    results: dict[str, bool] = {}
    for name in plugins:
        try:
            console.print(f"  Uninstalling [cyan]{name}[/cyan]...")
            uninstall_plugin(name)
            console.print(f"  Installing [cyan]{name}[/cyan]...")
            install_plugin(name)
            console.print(f"  [green]✓[/green] {name} reinstalled")
            results[name] = True
        except InstallerError as exc:
            console.print(f"  [red]✗[/red] {name}: {exc}")
            if Confirm.ask("  Retry?", default=False):
                try:
                    uninstall_plugin(name)
                    install_plugin(name)
                    console.print(f"  [green]✓[/green] {name} reinstalled")
                    results[name] = True
                except InstallerError as retry_exc:
                    console.print(f"  [red]✗[/red] {name}: {retry_exc}")
                    results[name] = False
            else:
                results[name] = False

    # Run wizard after reinstall if configs were reset
    if not args.skip_wizard:
        run_wizard(plugins, skip=False)

    succeeded = sum(1 for ok in results.values() if ok)
    failed_count = sum(1 for ok in results.values() if not ok)
    console.print(
        f"\n[bold]Summary:[/bold] {succeeded} succeeded, {failed_count} failed"
    )

    if failed_count:
        return EXIT_ERROR
    return EXIT_SUCCESS


def _uninstall(args) -> int:
    """Run the uninstall flow."""
    console = Console()
    state = detect_existing()
    display_detection(state, console)

    installed = get_installed_plugins()
    if not installed:
        console.print(
            "[yellow]No installed plugins found. Nothing to uninstall.[/yellow]"
        )
        return EXIT_SUCCESS

    plugins = list(installed)
    console.print(f"\n[bold]Uninstalling:[/bold] {', '.join(plugins)}")
    results: dict[str, bool] = {}
    for name in plugins:
        try:
            console.print(f"  Uninstalling [cyan]{name}[/cyan]...")
            uninstall_plugin(name)
            console.print(f"  [green]✓[/green] {name} uninstalled")
            results[name] = True
        except InstallerError as exc:
            console.print(f"  [red]✗[/red] {name}: {exc}")
            if Confirm.ask("  Retry?", default=False):
                try:
                    uninstall_plugin(name)
                    console.print(f"  [green]✓[/green] {name} uninstalled")
                    results[name] = True
                except InstallerError as retry_exc:
                    console.print(f"  [red]✗[/red] {name}: {retry_exc}")
                    results[name] = False
            else:
                results[name] = False

    if args.full_cleanup:
        console.print("\n[bold]Cleaning up config files...[/bold]")
        cleanup_config_files(console)

    succeeded = sum(1 for ok in results.values() if ok)
    failed_count = sum(1 for ok in results.values() if not ok)
    console.print(
        f"\n[bold]Summary:[/bold] {succeeded} succeeded, {failed_count} failed"
    )

    if failed_count:
        return EXIT_ERROR
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
