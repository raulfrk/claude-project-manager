# installer/flow/pre_install_phase.py
"""Pre-phase orchestrator for the installer flow.

Runs BEFORE the interactive (Textual or prompt_toolkit) phase. Handles:
 - existing-installation detection + confirm (update/reinstall/uninstall)
 - mode-specific confirms (reinstall: reset_configs + orphan prune; uninstall: full_cleanup)

Install mode skips detection — plugin_select handles per-plugin picks later.

Corrupt-yaml detection is handled inside WizardScreen (still Textual in P3);
it will move into this pre-phase in P4 when wizard ports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.cleanup import scan_stale_cache
from installer.detect import detect_existing
from installer.flow.confirm import ConfirmOption, confirm_with_options
from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm
from installer.flow.detection import show_detection_and_confirm
from installer.update import (
    _read_installed_version,
    _read_marketplace_versions,
)

if TYPE_CHECKING:
    from installer.detect import InstallState
    from installer.flow.detection import PluginDetectionRow


@dataclass(frozen=True)
class PreInstallResult:
    state: "InstallState | None"
    proceed: bool
    mode_options: dict[str, bool] = field(default_factory=dict)
    exit_code: int = 0
    error_message: str | None = None
    orphans_to_remove: list[str] = field(default_factory=list)


def _build_detection_rows(state: "InstallState") -> list["PluginDetectionRow"]:
    """Build (plugin, installed, available) rows used by show_detection_and_confirm."""
    from installer.flow.detection import PluginDetectionRow

    repo_versions = _read_marketplace_versions()
    rows: list[PluginDetectionRow] = []
    all_plugins = sorted(set(state.installed_plugins) | set(repo_versions.keys()))
    for name in all_plugins:
        installed_ver = None
        if state.cache_dir is not None and name in state.installed_plugins:
            installed_ver = _read_installed_version(state.cache_dir, name)
        available_ver = repo_versions.get(name)
        rows.append(
            PluginDetectionRow(
                plugin=name,
                installed_version=installed_ver,
                available_version=available_ver,
            )
        )
    return rows


def _cache_dir() -> Path:
    return Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"


def _marketplace_path() -> Path:
    here = Path(__file__).resolve().parent.parent
    bundled = here / "marketplace.json"
    if bundled.is_file():
        return bundled
    return here.parent / ".claude-plugin" / "marketplace.json"


_KNOWN_BUCKETS: tuple[str, ...] = ("proj", "worktree", "todoist", "trello", "jira")


def _check_corrupt_yaml(console: Console) -> bool:
    """Preload ~/.claude/{bucket}.yaml for known buckets. Prompt user on errors.

    Returns True if all yaml OK or user opts to continue with defaults.
    Returns False if user cancels.
    """
    claude_home = Path.home() / ".claude"
    errors: dict[str, Exception] = {}
    for bucket in _KNOWN_BUCKETS:
        path = claude_home / f"{bucket}.yaml"
        if not path.exists():
            continue
        try:
            load_existing_yaml(path)
        except ConfigLoadError as exc:
            errors[bucket] = exc.original if hasattr(exc, "original") else exc
    if errors:
        return show_corrupt_yaml_and_confirm(errors, console)
    return True


def pre_install_phase(mode: str, args: Any, console: Console) -> PreInstallResult:
    if not _check_corrupt_yaml(console):
        return PreInstallResult(state=None, proceed=False)

    if mode == "install":
        # Install mode: plugin_select handles per-plugin picks in the interactive phase.
        # No detection/confirm here.
        return PreInstallResult(state=None, proceed=True)

    if mode not in ("update", "reinstall", "uninstall"):
        return PreInstallResult(
            state=None,
            proceed=False,
            exit_code=2,
            error_message=f"Unknown mode: {mode}",
        )

    # update/reinstall/uninstall share the detection gate.
    state = detect_existing()
    rows = _build_detection_rows(state)
    title = f"Existing Installation — {mode.title()} Mode"
    if not show_detection_and_confirm(state, rows, title, console):
        return PreInstallResult(state=state, proceed=False)

    if mode == "update":
        # Update picks happen via select_updates in the interactive phase.
        return PreInstallResult(state=state, proceed=True)

    if mode == "reinstall":
        confirm = confirm_with_options(
            title="Reinstall Plugins",
            message=(
                "This will reinstall all installed plugins.\n"
                "A backup will be created before any changes."
            ),
            options=[
                ConfirmOption(
                    key="reset_configs",
                    label="Reset configs (remove proj.yaml, worktree.yaml)",
                    default=False,
                )
            ],
            console=console,
            variant="warning",
            confirm_label="Reinstall",
        )
        if not confirm.confirmed:
            return PreInstallResult(state=state, proceed=False)

        orphans: list[str] = []
        cache = _cache_dir()
        marketplace = _marketplace_path()
        if cache.is_dir() and marketplace.is_file():
            try:
                report = scan_stale_cache(cache, marketplace)
                if report.orphans:
                    orphan_names = list(report.orphans)
                    confirm_orph = confirm_with_options(
                        title="Remove Orphaned Plugins",
                        message=(
                            f"Found {len(orphan_names)} orphaned plugin dir(s) "
                            f"in cache:\n  {', '.join(orphan_names)}\n\n"
                            "These plugins are no longer in the marketplace. "
                            "Remove them?"
                        ),
                        options=[],
                        console=console,
                        variant="warning",
                        confirm_label="Remove",
                    )
                    if confirm_orph.confirmed:
                        orphans = orphan_names
            except (FileNotFoundError, OSError):
                pass

        return PreInstallResult(
            state=state,
            proceed=True,
            mode_options=confirm.options,
            orphans_to_remove=orphans,
        )

    # mode == "uninstall"
    confirm = confirm_with_options(
        title="Uninstall Plugins",
        message=(
            "This will remove all installed plugins.\n"
            "A backup will be created before removal."
        ),
        options=[
            ConfirmOption(
                key="full_cleanup",
                label="Full cleanup (remove configs + CLAUDE.md managed section)",
                default=False,
            )
        ],
        console=console,
        variant="error",
        confirm_label="Uninstall",
    )
    if not confirm.confirmed:
        return PreInstallResult(state=state, proceed=False)
    return PreInstallResult(state=state, proceed=True, mode_options=confirm.options)
