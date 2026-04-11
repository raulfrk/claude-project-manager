"""Dataclasses + diff/apply logic for managing ~/.claude/settings.json hooks.

Follows the Permissions/SettingsFile raw-field preservation pattern from
plugins/sandbox/server/server/lib/models.py so round-trips never drop unknown
keys. Reads and writes settings.json directly (JSON, not YAML) and only
touches the top-level ``hooks`` key.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml


class SettingsHooksError(Exception):
    """Raised when settings.json hooks cannot be read, parsed, or written."""


DiffKind = Literal["new", "changed", "removed", "unchanged"]


@dataclass
class SettingsHookDiff:
    """One row in the diff between desired and actual settings.json hook entries.

    cpm_id: the managed hook identifier (e.g. "proj-session-start-all")
    kind: new | changed | removed | unchanged
    desired: the resolved hook block from the plugin default (None if kind == "removed")
    actual: the current hook block in settings.json (None if kind == "new")
    event: e.g. "SessionStart"
    matchers: list of matcher names (e.g. ["startup", "resume", "clear", "compact"])
    """

    cpm_id: str
    kind: DiffKind
    event: str
    matchers: list[str]
    desired: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None


@dataclass
class HooksBlock:
    """Structured view of the top-level `hooks:` section in settings.json.

    Preserves the full raw dict so round-tripping through from_dict/to_dict
    never loses unknown keys (mirrors Permissions.from_dict/to_dict in
    plugins/sandbox/server/server/lib/models.py lines 12-40).

    events: {event_name: [matcher_block, ...]} — parsed convenience view.
    raw: the underlying dict (source of truth for round-trips).
    """

    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "HooksBlock":
        if not d or not isinstance(d, dict):
            return cls()
        events: dict[str, list[dict[str, Any]]] = {}
        for event, matchers in d.items():
            if isinstance(matchers, list):
                events[event] = [m for m in matchers if isinstance(m, dict)]
        return cls(events=events, raw=dict(d))

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.raw)
        for event, matchers in self.events.items():
            result[event] = matchers
        return result


@dataclass
class SettingsDocument:
    """Full ~/.claude/settings.json document with HooksBlock as a structured view.

    raw holds all top-level keys (permissions, env, etc.). hooks is the parsed
    view that diff/apply logic consumes. to_dict round-trips through raw so
    non-hook keys are never lost.
    """

    path: Path
    hooks: HooksBlock = field(default_factory=HooksBlock)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, path: Path, d: dict[str, Any] | None) -> "SettingsDocument":
        if not d or not isinstance(d, dict):
            return cls(path=path)
        hooks = HooksBlock.from_dict(d.get("hooks"))
        return cls(path=path, hooks=hooks, raw=dict(d))

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.raw)
        result["hooks"] = self.hooks.to_dict()
        return result


# ---- Plugin default file discovery ----

DEFAULT_SETTINGS_HOOKS_FILENAME = "default-settings-hooks.yaml"


def _load_plugin_default(plugin_dir: Path) -> dict[str, Any]:
    """Load plugins/<name>/.claude-plugin/default-settings-hooks.yaml. Empty dict on missing."""
    candidate = plugin_dir / ".claude-plugin" / DEFAULT_SETTINGS_HOOKS_FILENAME
    if not candidate.exists():
        return {}
    try:
        raw = candidate.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as exc:
        raise SettingsHooksError(f"Failed to parse {candidate}: {exc}") from exc
    if not isinstance(data, dict):
        return {}
    return data


def merge_settings_defaults(plugin_dirs: Iterable[Path]) -> dict[str, dict[str, Any]]:
    """Walk each plugin dir, load default-settings-hooks.yaml, merge by id.

    Returns: {cpm_id: entry_dict}. Hard error on duplicate IDs across plugins (AC14).
    Each entry has keys: id, event, matchers, command, [script, python, description].
    """
    merged: dict[str, dict[str, Any]] = {}
    seen_source: dict[str, Path] = {}
    for plugin_dir in plugin_dirs:
        data = _load_plugin_default(plugin_dir)
        entries = data.get("hooks")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cpm_id = entry.get("id")
            if not isinstance(cpm_id, str) or not cpm_id:
                continue
            if cpm_id in merged:
                prior = seen_source[cpm_id]
                raise SettingsHooksError(
                    f"Duplicate default-settings-hooks id '{cpm_id}' from "
                    f"{plugin_dir} (already defined by {prior})"
                )
            merged[cpm_id] = dict(entry)
            seen_source[cpm_id] = plugin_dir
    return merged


# ---- Command template resolution ----


def resolve_command_template(entry: dict[str, Any], plugin_cache_dir: Path) -> str:
    """Substitute {python}, {script}, {plugin_cache_dir} in the entry's command template.

    Returns the resolved command with a `# cpm:<id>` sentinel prepended as the
    first non-whitespace token of the command string (line-delimited for dual
    detection per AC15). The sentinel is on its own line so shell parsers treat
    it as a no-op comment.
    """
    cpm_id = str(entry.get("id") or "")
    python = str(entry.get("python") or "python3")
    script = str(entry.get("script") or "")
    command_template = str(entry.get("command") or "")
    resolved = (
        command_template.replace("{python}", python)
        .replace("{script}", script)
        .replace("{plugin_cache_dir}", str(plugin_cache_dir))
    )
    return f"# cpm:{cpm_id}\n{resolved}"


# ---- Dual detection ----

# Anchored, line-based sentinel regex. Explicit id charset prevents prefix
# collisions (asking for `foo` must not match `# cpm:foobar`). `re.MULTILINE`
# so `^...$` anchor each line within a multi-line command body. Trailing
# whitespace is tolerated; a mid-line `# cpm:x` comment (not at line start
# with only leading whitespace) will NOT match.
_SENTINEL_RE = re.compile(r"^\s*#\s*cpm:([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)


def _extract_cpm_id_from_command(command: str) -> str | None:
    """Return the first `# cpm:<id>` sentinel line id, or None.

    Strips `\\r` first so Windows line endings (`\\r\\n`) match cleanly.
    Requires a non-empty id composed of `[A-Za-z0-9_.-]` characters.
    Anchored `^...$` with `re.MULTILINE` — NOT a substring match — so
    `# cpm:foobar` will NOT match when the caller is looking for `foo`.
    """
    if not command:
        return None
    m = _SENTINEL_RE.search(command.replace("\r", ""))
    return m.group(1) if m else None


def is_managed_entry(matcher_block: dict[str, Any], cpm_id: str) -> bool:
    """True if matcher_block is managed by cpm for the given id.

    Dual detection per AC15:
    - ``__cpm_id`` field equals cpm_id (preferred)
    - OR any ``hooks[].command`` string contains a line-anchored
      ``# cpm:<id>`` sentinel

    Delegates sentinel parsing to :func:`_extract_cpm_id_from_command` so
    there is a single source of truth for the sentinel format. Exact
    equality comparison on the extracted id — NOT substring — prevents
    prefix collisions (e.g. query ``foo`` against sentinel ``# cpm:foobar``
    returns False).
    """
    if not isinstance(matcher_block, dict):
        return False
    if matcher_block.get("__cpm_id") == cpm_id:
        return True
    hooks_list = matcher_block.get("hooks")
    if isinstance(hooks_list, list):
        for h in hooks_list:
            if isinstance(h, dict):
                cmd = h.get("command")
                if isinstance(cmd, str):
                    if _extract_cpm_id_from_command(cmd) == cpm_id:
                        return True
    return False


def discover_managed_ids(
    doc: SettingsDocument,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``(event, cpm_id, matcher_block)`` for every managed matcher.

    Walks ``doc.hooks.events`` and returns one tuple per managed matcher
    occurrence. Dual detection mirrors :func:`is_managed_entry`:

    - ``matcher_block["__cpm_id"]`` field (preferred; must be non-empty str).
    - ``# cpm:<id>`` sentinel in any ``hooks[].command`` (recovery path).

    If both sources are present and disagree, the field wins.

    Return type is ``list[tuple[str, str, dict[str, Any]]]``, NOT ``set``,
    because ``dict`` is unhashable. Duplicate occurrences of the same
    ``(event, cpm_id)`` are PRESERVED — callers decide dedup semantics
    (``compute_settings_hooks_diff`` uses a seen-set so each unique
    ``(event, cpm_id)`` yields ONE ``removed`` diff; ``apply_settings_hooks_diffs``
    filters ALL occurrences in one pass for idempotency).

    Empty-string ``__cpm_id`` and empty sentinel suffixes are skipped.
    Non-dict matchers and non-dict hook entries are skipped.
    """
    out: list[tuple[str, str, dict[str, Any]]] = []
    for event, matchers in doc.hooks.events.items():
        for matcher in matchers:
            if not isinstance(matcher, dict):
                continue
            field_id = matcher.get("__cpm_id")
            cpm_id: str | None = None
            if isinstance(field_id, str) and field_id:
                cpm_id = field_id
            else:
                hooks_list = matcher.get("hooks")
                if isinstance(hooks_list, list):
                    for h in hooks_list:
                        if isinstance(h, dict):
                            cmd = h.get("command")
                            if isinstance(cmd, str):
                                extracted = _extract_cpm_id_from_command(cmd)
                                if extracted:
                                    cpm_id = extracted
                                    break
            if cpm_id:
                out.append((event, cpm_id, matcher))
    return out


# ---- Diff computation ----


def _read_settings_json(path: Path) -> dict[str, Any]:
    """Read settings.json with loud errors (unlike sandbox storage which swallows)."""
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsHooksError(f"Cannot read {path}: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SettingsHooksError(f"Malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsHooksError(
            f"{path}: top-level must be an object, got {type(data).__name__}"
        )
    return data


def compute_settings_hooks_diff(
    current_path: Path,
    plugin_dirs: Iterable[Path],
    *,
    mass_remove: bool = False,
) -> list[SettingsHookDiff]:
    """Compute per-hook-id diffs between desired (plugin defaults) and actual (settings.json).

    Orphan-detection strategy:

    1. Call :func:`discover_managed_ids` to find every managed matcher in
       ``settings.json`` independently of ``desired``.
    2. Key ``actual_by_event_id`` by ``(event, cpm_id)`` TUPLE (NOT by
       ``cpm_id`` alone) so cross-event collisions are preserved: an id
       desired in ``SessionStart`` but orphan in ``SessionEnd`` yields
       distinct diffs for each event.
    3. Emit ``new``/``changed``/``unchanged`` for ids in ``desired`` using
       ``(desired_event, cpm_id)`` lookup.
    4. Emit ``removed`` for discovered ``(event, cpm_id)`` pairs NOT in
       ``desired_keys``. A seen-set guard ensures duplicate occurrences
       within one ``(event, cpm_id)`` yield exactly one removed diff.

    Empty-desired guard: if ``desired == {}`` AND discovered is non-empty,
    this refuses to mass-remove and returns ``[]`` with a stderr warning
    unless the caller opts in via ``mass_remove=True``. Prevents a wall of
    spurious removals when plugin defaults fail to load.
    """
    resolved_path = current_path.resolve() if current_path.exists() else current_path
    current_raw = _read_settings_json(resolved_path)
    doc = SettingsDocument.from_dict(resolved_path, current_raw)

    desired = merge_settings_defaults(list(plugin_dirs))

    discovered = discover_managed_ids(doc)

    if not desired and discovered:
        print(
            f"Warning: no plugin defaults found but {len(discovered)} managed "
            "entries discovered in settings.json; refusing to mass-remove. "
            "Pass mass_remove=True to override.",
            file=sys.stderr,
        )
        if not mass_remove:
            return []

    # Key by (event, cpm_id) tuple — NOT cpm_id alone — to preserve
    # cross-event occurrences. First occurrence wins for the diff's
    # `actual` field.
    actual_by_event_id: dict[tuple[str, str], dict[str, Any]] = {}
    for event, cpm_id, matcher in discovered:
        actual_by_event_id.setdefault((event, cpm_id), matcher)

    diffs: list[SettingsHookDiff] = []

    # Build the set of desired (event, cpm_id) keys so the orphan loop
    # below can skip ids that are desired in the same event.
    desired_keys: set[tuple[str, str]] = set()
    for cpm_id, entry in desired.items():
        desired_event = str(entry.get("event") or "SessionStart")
        desired_keys.add((desired_event, cpm_id))

    for cpm_id, entry in desired.items():
        event = str(entry.get("event") or "SessionStart")
        matchers_list = list(entry.get("matchers") or [])
        key = (event, cpm_id)
        actual_matcher = actual_by_event_id.get(key)
        if actual_matcher is not None:
            desired_resolved = resolve_command_template(entry, Path())
            actual_cmds: list[str] = []
            actual_hooks = actual_matcher.get("hooks")
            if isinstance(actual_hooks, list):
                for h in actual_hooks:
                    if isinstance(h, dict):
                        cmd = h.get("command")
                        if isinstance(cmd, str):
                            actual_cmds.append(cmd)
            sentinel = f"# cpm:{cpm_id}\n"
            desired_body = desired_resolved.replace(sentinel, "")
            actual_bodies = [c.replace(sentinel, "") for c in actual_cmds]
            kind: DiffKind = "unchanged" if desired_body in actual_bodies else "changed"
            diffs.append(
                SettingsHookDiff(
                    cpm_id=cpm_id,
                    kind=kind,
                    event=event,
                    matchers=matchers_list,
                    desired=entry,
                    actual={"event": event, "matcher": actual_matcher},
                )
            )
        else:
            diffs.append(
                SettingsHookDiff(
                    cpm_id=cpm_id,
                    kind="new",
                    event=event,
                    matchers=matchers_list,
                    desired=entry,
                    actual=None,
                )
            )

    # Orphan loop: emit one `removed` diff per unique (event, cpm_id) not
    # desired in that event. Seen-set dedups duplicate occurrences within
    # the same (event, cpm_id).
    emitted_removed: set[tuple[str, str]] = set()
    for event, cpm_id, matcher in discovered:
        key = (event, cpm_id)
        if key in desired_keys:
            continue
        if key in emitted_removed:
            continue
        emitted_removed.add(key)
        diffs.append(
            SettingsHookDiff(
                cpm_id=cpm_id,
                kind="removed",
                event=event,
                matchers=[str(matcher.get("matcher") or "")],
                desired=None,
                actual={"event": event, "matcher": matcher},
            )
        )

    return diffs


# ---- Apply + backup ----


def _backup_with_retention(path: Path, keep: int = 5) -> Path:
    """Create a timestamped backup of path, keep only the most recent `keep` backups."""
    if not path.exists():
        return path
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_suffix(path.suffix + f".bak-{ts}")
    shutil.copy2(path, backup_path)

    parent = path.parent
    prefix = path.name + ".bak-"
    existing = sorted(
        [p for p in parent.iterdir() if p.name.startswith(prefix)],
        key=lambda p: p.stat().st_mtime,
    )
    while len(existing) > keep:
        old = existing.pop(0)
        try:
            old.unlink()
        except OSError:
            pass
    return backup_path


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Symlink-aware atomic write on same filesystem (mirrors sandbox storage.py:47)."""
    resolved = path.resolve() if path.exists() else path
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(resolved)


def apply_settings_hooks_diffs(
    current_path: Path,
    diffs: list[SettingsHookDiff],
    apply_ids: set[str],
    remove_ids: set[str] | None = None,
) -> None:
    """Apply selected diffs to settings.json. Short-circuits on empty diff (AC4).

    - ``apply_ids``: diffs with these cpm_ids are applied (new/changed).
    - ``remove_ids``: diffs with these cpm_ids have their managed blocks removed.
    - Creates a timestamped backup with 5-keep retention before writing (AC8).
    - Wrong top-level type aborts with SettingsHooksError.
    - Read-only file aborts with SettingsHooksError.
    """
    remove_ids = remove_ids or set()
    actionable = [d for d in diffs if d.cpm_id in apply_ids or d.cpm_id in remove_ids]
    if not actionable:
        return  # AC4 short-circuit

    resolved_path = current_path.resolve() if current_path.exists() else current_path
    current_raw = _read_settings_json(resolved_path)
    doc = SettingsDocument.from_dict(resolved_path, current_raw)

    _backup_with_retention(resolved_path)

    # Buffer new managed matchers per event so we can sort by cpm_id before
    # append — deterministic order prevents platform-dependent churn from
    # plugin_dirs iteration order.
    pending_appends: dict[str, list[dict[str, Any]]] = {}

    # Sort actionable by cpm_id so the final append order is deterministic
    # regardless of how plugin_dirs were iterated.
    for diff in sorted(actionable, key=lambda d: d.cpm_id):
        event = diff.event
        if diff.cpm_id in remove_ids:
            # Filter-all: `is_managed_entry` checks all matchers in the
            # event, so duplicates with the same cpm_id are removed in one
            # pass (idempotent).
            matchers_list = doc.hooks.events.get(event, [])
            doc.hooks.events[event] = [
                m for m in matchers_list if not is_managed_entry(m, diff.cpm_id)
            ]
            continue
        if diff.cpm_id not in apply_ids:
            continue
        matchers_list = doc.hooks.events.setdefault(event, [])
        doc.hooks.events[event] = [
            m for m in matchers_list if not is_managed_entry(m, diff.cpm_id)
        ]
        if diff.desired is None:
            continue
        for matcher_name in diff.matchers:
            resolved_cmd = resolve_command_template(diff.desired, Path())
            new_block = {
                "matcher": matcher_name,
                "__cpm_id": diff.cpm_id,
                "hooks": [{"command": resolved_cmd, "type": "command"}],
            }
            pending_appends.setdefault(event, []).append(new_block)

    # Append buffered managed matchers in sorted order by cpm_id (already
    # sorted above, but re-sort defensively in case multiple matchers
    # within a single diff reordered insertion).
    for event, blocks in pending_appends.items():
        blocks_sorted = sorted(blocks, key=lambda b: str(b.get("__cpm_id") or ""))
        doc.hooks.events.setdefault(event, [])
        doc.hooks.events[event].extend(blocks_sorted)

    try:
        _atomic_write_json(resolved_path, doc.to_dict())
    except OSError as exc:
        raise SettingsHooksError(f"Cannot write {resolved_path}: {exc}") from exc
