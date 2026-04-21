"""Entry point for the installer."""

from __future__ import annotations

import sys
from typing import IO

from rich.console import Console

from rich.prompt import Confirm

from installer.cleanup import (
    _cache_dir_for_reinstall,
    _marketplace_path_for_reinstall,
    prune_orphaned_plugins,
    prune_stale_versions,
    scan_stale_cache,
)
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
from installer.flow.console import get_console
from installer.flow.installer_flow import run_installer_flow
from installer.plugin_cli import (
    add_marketplace,
    check_marketplace_registered,
    get_available_plugins,
    get_installed_plugins,
    install_plugin,
    remove_marketplace,
)
from installer.flow.yn import install_confirm_patch
from installer.tty_guard import tty_guard
from installer.uninstall import cleanup_config_files
from installer.tui import load_plugins, select_plugins
from installer.wizard import run_wizard
from installer.local_marketplace import ensure_local_clone
from installer.plugin_cli import _MARKETPLACE_SOURCE

# Exit codes
EXIT_SUCCESS = 0
EXIT_CANCELLED = 1
EXIT_ERROR = 2


def _resolve_marketplace_source(args) -> tuple[str, str | None]:
    """Return (source, branch) to pass to ``add_marketplace``.

    With ``--local-marketplace`` set, clones (or updates) the repo locally
    and returns the absolute path as the marketplace source. The branch is
    returned as ``None`` because ``ensure_local_clone`` already checks out
    the target branch inside the clone.

    Without ``--local-marketplace``, returns the hardcoded GitHub short ref
    and passes the raw ``--branch`` flag through.
    """
    if getattr(args, "local_marketplace", False):
        branch = getattr(args, "branch", None)
        local_path = ensure_local_clone(branch=branch)
        return (str(local_path), None)
    return (_MARKETPLACE_SOURCE, getattr(args, "branch", None))


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

    # 3. Ensure marketplace is registered (optionally from a local clone)
    try:
        source, branch = _resolve_marketplace_source(args)
    except InstallerError as exc:
        console.print(f"[red]Failed to prepare marketplace source:[/] {exc}")
        return EXIT_ERROR
    source_is_local = getattr(args, "local_marketplace", False)
    # For display: keep the raw branch so users see it even when source is local
    # (branch is consumed by ensure_local_clone and passed as None to add_marketplace).
    raw_branch = getattr(args, "branch", None)
    display_branch = raw_branch if source_is_local else branch
    with console.status("[bold]Checking marketplace registration..."):
        if not check_marketplace_registered():
            branch_msg = f" (branch: {display_branch})" if display_branch else ""
            source_msg = " from local clone" if source_is_local else ""
            console.print(
                f"Marketplace not registered. Adding{source_msg}...{branch_msg}"
            )
            add_marketplace(source=source, branch=branch)
            console.print("[green]Marketplace registered.[/green]")
        elif source_is_local or branch:
            if source_is_local and raw_branch:
                label = f"local clone (branch {raw_branch})"
            elif source_is_local:
                label = "local clone"
            else:
                label = f"branch {branch}"
            console.print(f"Re-adding marketplace from {label}")
            remove_marketplace()
            add_marketplace(source=source, branch=branch)
            console.print(f"[green]Marketplace updated from {label}.[/green]")
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
            console.print(
                f"  [dim]⊘ {name} already installed — use --reinstall to reinstall[/dim]"
            )
            results[name] = "skipped"
            continue

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

    plugins = list(installed)
    try:
        source, branch = _resolve_marketplace_source(args)
    except InstallerError as exc:
        console.print(f"[red]Failed to prepare marketplace source:[/] {exc}")
        return EXIT_ERROR
    source_is_local = getattr(args, "local_marketplace", False)
    raw_branch = getattr(args, "branch", None)

    console.print(f"\n[bold]Reinstalling:[/bold] {', '.join(plugins)}")

    # Prune stale cache versions and orphaned plugins before reinstall
    cache_dir = _cache_dir_for_reinstall()
    marketplace_path = _marketplace_path_for_reinstall()

    if cache_dir.is_dir() and marketplace_path.is_file():
        try:
            report = scan_stale_cache(cache_dir, marketplace_path)
        except (FileNotFoundError, OSError) as exc:
            console.print(f"[yellow]Skipping cache cleanup: {exc}[/yellow]")
        else:
            deleted_stale = prune_stale_versions(cache_dir, report)
            if deleted_stale:
                console.print(
                    f"[dim]Pruned {len(deleted_stale)} stale version dir(s)[/dim]"
                )
            if report.orphans:
                console.print(
                    f"[yellow]Found {len(report.orphans)} orphaned plugin(s): "
                    f"{', '.join(report.orphans)}[/yellow]"
                )
                if Confirm.ask("Remove orphaned plugin cache dirs?", default=True):
                    deleted_orph = prune_orphaned_plugins(cache_dir, report.orphans)
                    console.print(
                        f"[dim]Removed {len(deleted_orph)} orphan plugin(s)[/dim]"
                    )
                else:
                    console.print(
                        "[dim]Leaving orphans in place; rerun --reinstall anytime.[/dim]"
                    )

    # Remove marketplace (uninstalls all plugins) then re-add
    with console.status("[bold]Removing marketplace...[/bold]"):
        remove_marketplace()
    console.print("  [green]✓[/green] Marketplace removed")

    if source_is_local and raw_branch:
        label = f"from local clone (branch {raw_branch})"
    elif source_is_local:
        label = "from local clone"
    elif branch:
        label = f"from branch {branch}"
    else:
        label = ""
    status_msg = f" {label}" if label else ""
    with console.status(f"[bold]Re-adding marketplace{status_msg}...[/bold]"):
        add_marketplace(source=source, branch=branch)
    console.print(f"  [green]✓[/green] Marketplace re-added{status_msg}")

    results: dict[str, bool] = {}
    for name in plugins:
        try:
            with console.status(f"[bold]Installing {name}...[/bold]"):
                install_plugin(name)
            console.print(f"  [green]✓[/green] {name} reinstalled")
            results[name] = True
        except InstallerError as exc:
            console.print(f"  [red]✗[/red] {name}: {exc}")
            if Confirm.ask("  Retry?", default=False):
                try:
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
        f"\n[bold]Summary:[/bold] {succeeded} reinstalled, {failed_count} failed"
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

    try:
        with console.status("[bold]Removing marketplace...[/bold]"):
            remove_marketplace()
        console.print(
            f"  [green]✓[/green] Marketplace removed ({len(plugins)} plugins uninstalled)"
        )
    except InstallerError as exc:
        console.print(f"  [red]✗[/red] Failed to remove marketplace: {exc}")
        if args.full_cleanup:
            console.print("\n[bold]Cleaning up config files...[/bold]")
            cleanup_config_files(console)
        return EXIT_ERROR

    if args.full_cleanup:
        console.print("\n[bold]Cleaning up config files...[/bold]")
        cleanup_config_files(console)

    console.print(f"\n[bold]Summary:[/bold] {len(plugins)} uninstalled")
    return EXIT_SUCCESS


def main() -> int:
    """Parse arguments and dispatch to the appropriate flow."""
    # Widen Rich's Confirm to accept yes/no + case-insensitive before any
    # prompt fires. Idempotent.
    install_confirm_patch()
    # tty_guard wraps the whole run: if any subprocess or interactive dialog
    # leaks raw-mode termios (ICRNL cleared → Enter echoes as ^M, input() hangs),
    # the user's shell is restored before we exit.
    with tty_guard():
        return _main_inner()


def _main_inner() -> int:
    lock_fh: IO | None = None

    try:
        parser = build_parser()
        args = parser.parse_args()

        # Safety checks
        check_root()

        # Migration shortcut — bypasses the install TUI + Claude CLI
        # prerequisite check. Running a migration does not require Claude CLI.
        # getattr() is defensive: tests stub parser.parse_args() with bare
        # Namespaces that don't know about these flags.
        if getattr(args, "migrate", False):
            import sys as _sys

            from installer.cli import load_project_list
            from installer.migrations.entry import (
                run_dry_run,
                run_pending_migrations,
            )

            if getattr(args, "dry_run", False):
                return run_dry_run(load_project_list())
            return run_pending_migrations(
                load_project_list(),
                interactive=_sys.stdin.isatty(),
                strict_resync=getattr(args, "strict_resync", False),
                backup_retain_days=getattr(args, "backup_retain", None),
            )

        # Full install/upgrade/uninstall paths still require the Claude CLI
        # and a process-level lock.
        check_prerequisites()
        lock_fh = acquire_lock()

        # --full-cleanup without --uninstall implies --uninstall --full-cleanup
        if args.full_cleanup and not args.uninstall:
            args.uninstall = True

        # Determine mode for TUI routing
        if args.reinstall:
            mode = "reinstall"
        elif args.uninstall:
            mode = "uninstall"
        else:
            mode = "install"

        if args.no_tui:
            # Plain Rich-based flow
            if mode == "reinstall":
                return _reinstall(args)
            elif mode == "uninstall":
                return _uninstall(args)
            else:
                return _install(args)
        else:
            # Rich-based flow via run_installer_flow
            return run_installer_flow(mode, args, get_console())

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
