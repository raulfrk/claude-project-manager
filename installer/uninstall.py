"""Uninstall logic for the installer."""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

from installer.detect import (
    InstallState,
    create_backup,
    detect_existing,
    display_detection,
)
from installer.errors import UserCancelled
from installer.plugin_cli import get_installed_plugins


def remove_plugins(
    plugins: list[str],
    state: InstallState,
    console: Console | None = None,
) -> dict[str, bool]:
    """Remove installed plugins from the cache directory.

    Args:
        plugins: Plugin names to remove.
        state: Current installation state.
        console: Rich console for output.

    Returns:
        Dict of plugin_name -> success boolean.
    """
    if console is None:
        console = Console()

    if state.cache_dir is None:
        console.print("[yellow]No cache directory found. Nothing to remove.[/yellow]")
        return {p: True for p in plugins}

    results: dict[str, bool] = {}
    for plugin_name in plugins:
        plugin_path = state.cache_dir / plugin_name
        if not plugin_path.exists():
            console.print(f"  [dim]{plugin_name}: not installed[/dim]")
            results[plugin_name] = True
            continue

        console.print(f"  Removing [bold]{plugin_name}[/bold]...", end=" ")
        try:
            shutil.rmtree(plugin_path)
            console.print("[green]done[/green]")
            results[plugin_name] = True
        except (OSError, PermissionError) as exc:
            console.print(f"[red]failed: {exc}[/red]")
            results[plugin_name] = False

    return results


def cleanup_config_files(console: Console | None = None) -> None:
    """Remove proj.yaml and worktree.yaml config files.

    Args:
        console: Rich console for output.
    """
    if console is None:
        console = Console()

    config_files = [
        Path.home() / ".claude" / "proj.yaml",
        Path.home() / ".claude" / "worktree.yaml",
    ]

    for path in config_files:
        if path.exists():
            try:
                path.unlink()
                console.print(f"  Removed [bold]{path}[/bold]")
            except (OSError, PermissionError) as exc:
                console.print(f"  [red]Failed to remove {path}: {exc}[/red]")
        else:
            console.print(f"  [dim]{path.name}: not found[/dim]")


def run_uninstall(full_cleanup: bool = False, console: Console | None = None) -> None:
    """Detect installation, confirm, remove plugins, and optionally clean configs.

    Args:
        full_cleanup: If True, also remove config files (proj.yaml, worktree.yaml).
        console: Rich console for output.

    Raises:
        UserCancelled: If the user declines the confirmation prompt.
    """
    if console is None:
        console = Console()

    # Detect current state
    state = detect_existing()
    display_detection(state, console)

    if not state.installed_plugins and state.cache_dir is None:
        console.print("\n[dim]No installed plugins found. Nothing to uninstall.[/dim]")
        return

    # Confirmation
    action = (
        "uninstall all plugins and remove config files"
        if full_cleanup
        else "uninstall all plugins"
    )
    if not Confirm.ask(
        f"\n[bold]This will {action}.[/bold] Continue?",
        default=False,
        console=console,
    ):
        raise UserCancelled("Uninstall cancelled by user.")

    # Create backup
    backup_dir = create_backup(state)
    console.print(f"[dim]Backup created at {backup_dir}[/dim]\n")

    # Remove plugins
    console.print("[bold]Removing plugins...[/bold]")
    plugins_to_remove = get_installed_plugins()
    results = remove_plugins(plugins_to_remove, state, console)

    # Remove marketplace and cache directories if they're now empty
    for dir_path, label in [
        (state.cache_dir, "cache"),
        (state.marketplace_dir, "marketplace"),
    ]:
        if dir_path is not None and dir_path.exists():
            try:
                remaining = list(dir_path.iterdir())
                if not remaining:
                    dir_path.rmdir()
                    console.print(f"  Removed empty {label} directory")
            except OSError:
                pass

    # Config cleanup
    if full_cleanup:
        console.print("\n[bold]Cleaning up config files...[/bold]")
        cleanup_config_files(console)

    # Summary
    succeeded = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    console.print(
        f"\n[bold]Uninstall complete:[/bold] {succeeded} removed, {failed} failed"
    )
    if backup_dir:
        console.print(f"[dim]Backup available at {backup_dir}[/dim]")
