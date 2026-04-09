"""Diff engine for default-hooks.yaml files against the current hooks.yaml."""

from __future__ import annotations

import contextlib
import difflib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class HookDiff:
    """Represents the diff for a single hook between current and proposed state."""

    hook_id: str
    status: str  # "new" | "changed" | "removed"
    current_yaml: str | None  # YAML text of current hook (None if new)
    proposed_yaml: str | None  # YAML text of proposed hook (None if removed)
    unified_diff: str  # difflib.unified_diff output


def merge_defaults(plugin_dirs: list[Path]) -> dict[str, Any]:
    """Load and merge all default-hooks.yaml files from plugin dirs.

    For each dir, looks for ``.claude-plugin/default-hooks.yaml`` first,
    then ``default-hooks.yaml`` as fallback.  Parses YAML, merges hooks by ID
    (later plugin overwrites earlier on conflict).  Also merges ``settings``
    and ``servers`` sections.

    Returns ``{"settings": {...}, "servers": {...}, "hooks": {id: {...}}}``.
    """
    merged: dict[str, Any] = {"settings": {}, "servers": {}, "hooks": {}}

    for plugin_dir in plugin_dirs:
        # Try .claude-plugin/default-hooks.yaml first, then root
        candidates = [
            plugin_dir / ".claude-plugin" / "default-hooks.yaml",
            plugin_dir / "default-hooks.yaml",
        ]
        found: Path | None = None
        for candidate in candidates:
            if candidate.is_file():
                found = candidate
                break

        if found is None:
            continue

        try:
            raw = yaml.safe_load(found.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            logger.warning("Malformed YAML in %s — skipping", found)
            continue
        except OSError:
            logger.warning("Could not read %s — skipping", found)
            continue

        if not isinstance(raw, dict):
            logger.warning(
                "Expected dict in %s, got %s — skipping", found, type(raw).__name__
            )
            continue

        # Merge settings
        if isinstance(raw.get("settings"), dict):
            merged["settings"].update(raw["settings"])

        # Merge servers
        if isinstance(raw.get("servers"), dict):
            merged["servers"].update(raw["servers"])

        # Merge hooks by ID
        hooks_list = raw.get("hooks", [])
        if not isinstance(hooks_list, list):
            logger.warning("hooks key in %s is not a list — skipping hooks", found)
            continue

        for hook in hooks_list:
            if not isinstance(hook, dict):
                continue
            hook_id = hook.get("id")
            if not hook_id or not isinstance(hook_id, str):
                continue
            if hook_id in merged["hooks"]:
                logger.warning(
                    "Duplicate hook ID %r — overwriting with definition from %s",
                    hook_id,
                    found,
                )
            merged["hooks"][hook_id] = hook

    return merged


def compute_hooks_diff(current_path: Path, plugin_dirs: list[Path]) -> list[HookDiff]:
    """Compute per-hook diff between current hooks.yaml and merged defaults.

    Custom hooks (IDs not present in any default-hooks.yaml) are excluded
    from the diff — they are left untouched.
    """
    # Load current hooks.yaml
    current_hooks: dict[str, Any] = {}
    if current_path.is_file():
        try:
            raw = yaml.safe_load(current_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            logger.warning("Malformed YAML in %s — treating as empty", current_path)
            raw = None
        except OSError:
            raw = None

        if isinstance(raw, dict):
            hooks_list = raw.get("hooks", [])
            if isinstance(hooks_list, list):
                for hook in hooks_list:
                    if isinstance(hook, dict) and isinstance(hook.get("id"), str):
                        current_hooks[hook["id"]] = hook

    # Merge defaults from all plugin dirs
    merged = merge_defaults(plugin_dirs)
    default_ids = set(merged["hooks"].keys())

    diffs: list[HookDiff] = []

    # Check each hook in merged defaults
    for hook_id, proposed_data in merged["hooks"].items():
        proposed_yaml = _hook_to_yaml(hook_id, proposed_data)

        if hook_id not in current_hooks:
            # New hook
            diff_text = "".join(
                difflib.unified_diff(
                    [],
                    proposed_yaml.splitlines(keepends=True),
                    fromfile=f"a/{hook_id}",
                    tofile=f"b/{hook_id}",
                )
            )
            diffs.append(
                HookDiff(
                    hook_id=hook_id,
                    status="new",
                    current_yaml=None,
                    proposed_yaml=proposed_yaml,
                    unified_diff=diff_text,
                )
            )
        else:
            # Exists — check if changed
            current_yaml = _hook_to_yaml(hook_id, current_hooks[hook_id])
            if current_yaml == proposed_yaml:
                continue  # Identical — no diff needed

            diff_text = "".join(
                difflib.unified_diff(
                    current_yaml.splitlines(keepends=True),
                    proposed_yaml.splitlines(keepends=True),
                    fromfile=f"a/{hook_id}",
                    tofile=f"b/{hook_id}",
                )
            )
            diffs.append(
                HookDiff(
                    hook_id=hook_id,
                    status="changed",
                    current_yaml=current_yaml,
                    proposed_yaml=proposed_yaml,
                    unified_diff=diff_text,
                )
            )

    # Check for hooks in current that were in defaults but are no longer
    for hook_id, current_data in current_hooks.items():
        if hook_id in default_ids and hook_id not in merged["hooks"]:
            # This shouldn't happen (default_ids == merged["hooks"].keys()),
            # but guard anyway
            current_yaml = _hook_to_yaml(hook_id, current_data)
            diff_text = "".join(
                difflib.unified_diff(
                    current_yaml.splitlines(keepends=True),
                    [],
                    fromfile=f"a/{hook_id}",
                    tofile=f"b/{hook_id}",
                )
            )
            diffs.append(
                HookDiff(
                    hook_id=hook_id,
                    status="removed",
                    current_yaml=current_yaml,
                    proposed_yaml=None,
                    unified_diff=diff_text,
                )
            )

    # Detect hooks that exist in current with a source marker matching a default ID
    # but are no longer in the new defaults (removed upstream)
    for hook_id, current_data in current_hooks.items():
        if hook_id not in default_ids:
            # Check if this hook was originally from defaults via source field
            source = current_data.get("source")
            if isinstance(source, str) and source.startswith("default:"):
                # Was a default hook that's been removed from defaults
                current_yaml = _hook_to_yaml(hook_id, current_data)
                diff_text = "".join(
                    difflib.unified_diff(
                        current_yaml.splitlines(keepends=True),
                        [],
                        fromfile=f"a/{hook_id}",
                        tofile=f"b/{hook_id}",
                    )
                )
                diffs.append(
                    HookDiff(
                        hook_id=hook_id,
                        status="removed",
                        current_yaml=current_yaml,
                        proposed_yaml=None,
                        unified_diff=diff_text,
                    )
                )

    return diffs


def apply_diffs(
    current_path: Path,
    diffs: list[HookDiff],
    apply_ids: set[str],
    remove_ids: set[str],
) -> None:
    """Apply selected diffs to hooks.yaml.

    For each diff whose ``hook_id`` is in *apply_ids*, the hook is added or
    replaced.  For each diff whose ``hook_id`` is in *remove_ids*, the hook
    is deleted.  All other hooks are left untouched.
    """
    # Load current hooks.yaml (or start fresh)
    current_data: dict[str, Any] = {"hooks": []}
    if current_path.is_file():
        try:
            raw = yaml.safe_load(current_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            raw = None
        if isinstance(raw, dict):
            current_data = raw

    if not isinstance(current_data.get("hooks"), list):
        current_data["hooks"] = []

    # Build lookup of current hooks by ID
    hooks_by_id: dict[str, dict[str, Any]] = {}
    for hook in current_data["hooks"]:
        if isinstance(hook, dict) and isinstance(hook.get("id"), str):
            hooks_by_id[hook["id"]] = hook

    # Build a map of proposed hooks from diffs
    proposed_hooks: dict[str, dict[str, Any]] = {}
    for diff in diffs:
        if diff.proposed_yaml is not None:
            try:
                parsed = yaml.safe_load(diff.proposed_yaml)
                if isinstance(parsed, dict):
                    proposed_hooks[diff.hook_id] = parsed
            except yaml.YAMLError:
                continue

    # Apply additions/updates
    for hook_id in apply_ids:
        if hook_id in proposed_hooks:
            hooks_by_id[hook_id] = proposed_hooks[hook_id]

    # Apply removals
    for hook_id in remove_ids:
        hooks_by_id.pop(hook_id, None)

    # Rebuild hooks list preserving order of existing hooks, appending new ones
    seen: set[str] = set()
    new_hooks: list[dict[str, Any]] = []
    for hook in current_data["hooks"]:
        if isinstance(hook, dict) and isinstance(hook.get("id"), str):
            hid = hook["id"]
            if hid in hooks_by_id and hid not in seen:
                new_hooks.append(hooks_by_id[hid])
                seen.add(hid)
        else:
            # Preserve non-standard entries
            new_hooks.append(hook)

    # Append any new hooks not in the original list
    for hid, hook_data in hooks_by_id.items():
        if hid not in seen:
            new_hooks.append(hook_data)

    current_data["hooks"] = new_hooks
    content = yaml.dump(current_data, default_flow_style=False, sort_keys=False)
    _atomic_write(current_path, content)


def _hook_to_yaml(hook_id: str, hook_data: dict[str, Any]) -> str:
    """Render a single hook as YAML text for diff display.

    Produces a consistent representation by dumping just the hook dict,
    ensuring the ``id`` field is always present.
    """
    data = dict(hook_data)
    data["id"] = hook_id
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise
