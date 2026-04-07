"""Update and reinstall logic for the installer."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from installer.detect import InstallState, create_backup
from installer.errors import InstallerError

# Marketplace JSON bundled with the installer
_MARKETPLACE_PATH = (
    Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
)

# Recovery file for rollback on failure
_RECOVERY_PATH = Path.home() / ".claude" / "backups" / "cpm-recovery.json"


def _read_marketplace_versions(marketplace_path: Path | None = None) -> dict[str, str]:
    """Read plugin versions from the bundled marketplace.json."""
    path = marketplace_path or _MARKETPLACE_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["name"]: entry.get("version", "0.0.0")
        for entry in data.get("plugins", [])
    }


def _read_installed_version(cache_dir: Path, plugin_name: str) -> str | None:
    """Read the version from an installed plugin's plugin.json in the cache."""
    plugin_json = cache_dir / plugin_name / "plugin.json"
    if not plugin_json.exists():
        # Also check .claude-plugin subdirectory
        plugin_json = cache_dir / plugin_name / ".claude-plugin" / "plugin.json"
    if not plugin_json.exists():
        return None
    try:
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        return data.get("version")
    except (OSError, json.JSONDecodeError):
        return None


def compare_versions(
    state: InstallState, marketplace_path: Path | None = None
) -> dict[str, tuple[str, str]]:
    """Compare installed plugin versions against the repo marketplace.json.

    Returns a dict of plugin_name -> (installed_version, repo_version) for
    plugins where versions differ. Only considers plugins that are currently
    installed.
    """
    repo_versions = _read_marketplace_versions(marketplace_path)

    if state.cache_dir is None:
        return {}

    diffs: dict[str, tuple[str, str]] = {}
    for plugin_name in state.installed_plugins:
        installed_ver = _read_installed_version(state.cache_dir, plugin_name)
        repo_ver = repo_versions.get(plugin_name)
        if installed_ver is None or repo_ver is None:
            continue
        if installed_ver != repo_ver:
            diffs[plugin_name] = (installed_ver, repo_ver)

    return diffs


def display_version_diff(diffs: dict[str, tuple[str, str]], console: Console) -> None:
    """Display a Rich table showing version differences per plugin."""
    if not diffs:
        console.print("[green]All installed plugins are up to date.[/green]")
        return

    table = Table(title="Plugin Version Changes", show_lines=False)
    table.add_column("Plugin", style="bold")
    table.add_column("Installed", style="yellow")
    table.add_column("", justify="center")
    table.add_column("Available", style="green")

    for name in sorted(diffs):
        old_ver, new_ver = diffs[name]
        table.add_row(name, old_ver, "->", new_ver)

    console.print(table)


def _remove_plugin(cache_dir: Path, plugin_name: str) -> bool:
    """Remove a plugin from the cache directory. Returns True on success."""
    plugin_path = cache_dir / plugin_name
    if not plugin_path.exists():
        return True
    try:
        shutil.rmtree(plugin_path)
        return True
    except (OSError, PermissionError):
        return False


def _install_plugin(cache_dir: Path, plugin_name: str, source_dir: Path) -> bool:
    """Install a plugin by copying its source to the cache directory.

    Uses the plugin source directory from the repo.
    Returns True on success.
    """
    dest = cache_dir / plugin_name
    try:
        shutil.copytree(source_dir, dest, dirs_exist_ok=True)
        # Run uv sync if pyproject.toml exists
        pyproject = dest / "pyproject.toml"
        if pyproject.exists():
            subprocess.run(
                ["uv", "sync"],
                cwd=str(dest),
                check=True,
                capture_output=True,
                timeout=120,
            )
        return True
    except (
        OSError,
        PermissionError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return False


def _resolve_plugin_source(plugin_name: str) -> Path:
    """Resolve the source directory for a plugin in the repo."""
    repo_root = Path(__file__).resolve().parent.parent
    return repo_root / "plugins" / plugin_name


def _write_recovery(
    backup_dir: Path | None,
    selected_plugins: list[str],
    failed: list[str],
) -> None:
    """Write a recovery JSON file for failed operations."""
    recovery = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "backup_dir": str(backup_dir) if backup_dir else None,
        "selected_plugins": selected_plugins,
        "failed_plugins": failed,
        "action": "restore backup and retry",
    }
    _RECOVERY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RECOVERY_PATH.write_text(json.dumps(recovery, indent=2), encoding="utf-8")


def run_update(
    selected_plugins: list[str],
    state: InstallState,
    console: Console | None = None,
) -> dict[str, bool]:
    """Update plugins: remove and reinstall while preserving configs.

    Args:
        selected_plugins: Plugin names to update.
        state: Current installation state.
        console: Rich console for output.

    Returns:
        Dict of plugin_name -> success boolean.

    Raises:
        InstallerError: If cache directory is not found.
    """
    if console is None:
        console = Console()

    if state.cache_dir is None:
        raise InstallerError("No cache directory found. Nothing to update.")

    # Create backup before modifying anything
    backup_dir = create_backup(state)
    console.print(f"[dim]Backup created at {backup_dir}[/dim]")

    results: dict[str, bool] = {}
    failed: list[str] = []

    for plugin_name in selected_plugins:
        source = _resolve_plugin_source(plugin_name)
        if not source.is_dir():
            console.print(
                f"[yellow]Skipping {plugin_name}: source not found at {source}[/yellow]"
            )
            results[plugin_name] = False
            failed.append(plugin_name)
            continue

        console.print(f"  Updating [bold]{plugin_name}[/bold]...", end=" ")

        # Remove old version
        if not _remove_plugin(state.cache_dir, plugin_name):
            console.print("[red]failed (removal)[/red]")
            results[plugin_name] = False
            failed.append(plugin_name)
            continue

        # Install new version
        if _install_plugin(state.cache_dir, plugin_name, source):
            console.print("[green]done[/green]")
            results[plugin_name] = True
        else:
            console.print("[red]failed (install)[/red]")
            results[plugin_name] = False
            failed.append(plugin_name)

    if failed:
        _write_recovery(backup_dir, selected_plugins, failed)
        console.print(
            "\n[red]Some plugins failed."
            f" Recovery info written to {_RECOVERY_PATH}[/red]"
        )

    return results


def run_reinstall(
    selected_plugins: list[str],
    state: InstallState,
    console: Console | None = None,
) -> dict[str, bool]:
    """Reinstall plugins: remove and reinstall, prompting for config handling.

    Args:
        selected_plugins: Plugin names to reinstall.
        state: Current installation state.
        console: Rich console for output.

    Returns:
        Dict of plugin_name -> success boolean.

    Raises:
        InstallerError: If cache directory is not found.
    """
    if console is None:
        console = Console()

    if state.cache_dir is None:
        raise InstallerError("No cache directory found. Nothing to reinstall.")

    # Prompt for config handling
    console.print("\n[bold]Config handling for reinstall:[/bold]")
    console.print("  1) [bold]Keep[/bold] - preserve existing configuration files")
    console.print("  2) [bold]Reset[/bold] - remove configs and start fresh")
    choice = Prompt.ask("Select an option", choices=["1", "2"], default="1")
    reset_configs = choice == "2"

    # Create backup
    backup_dir = create_backup(state)
    console.print(f"[dim]Backup created at {backup_dir}[/dim]")

    if reset_configs:
        # Remove config files
        for config_path in (state.proj_yaml, state.worktree_yaml):
            if config_path is not None and config_path.exists():
                try:
                    config_path.unlink()
                    console.print(f"[dim]Removed {config_path.name}[/dim]")
                except OSError as exc:
                    console.print(
                        "[yellow]Warning: could not remove"
                        f" {config_path}: {exc}[/yellow]"
                    )

    results: dict[str, bool] = {}
    failed: list[str] = []

    for plugin_name in selected_plugins:
        source = _resolve_plugin_source(plugin_name)
        if not source.is_dir():
            console.print(
                f"[yellow]Skipping {plugin_name}: source not found at {source}[/yellow]"
            )
            results[plugin_name] = False
            failed.append(plugin_name)
            continue

        console.print(f"  Reinstalling [bold]{plugin_name}[/bold]...", end=" ")

        # Remove existing
        if not _remove_plugin(state.cache_dir, plugin_name):
            console.print("[red]failed (removal)[/red]")
            results[plugin_name] = False
            failed.append(plugin_name)
            continue

        # Install fresh
        if _install_plugin(state.cache_dir, plugin_name, source):
            console.print("[green]done[/green]")
            results[plugin_name] = True
        else:
            console.print("[red]failed (install)[/red]")
            results[plugin_name] = False
            failed.append(plugin_name)

    if failed:
        _write_recovery(backup_dir, selected_plugins, failed)
        console.print(
            "\n[red]Some plugins failed."
            f" Recovery info written to {_RECOVERY_PATH}[/red]"
        )

    return results
