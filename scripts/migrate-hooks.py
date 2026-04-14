#!/usr/bin/env python3
"""Remove stale/duplicate hooks from ~/.claude/hooks.yaml.

Usage:
    python scripts/migrate-hooks.py           # apply changes
    python scripts/migrate-hooks.py --dry-run # preview only
"""

import sys
import yaml
from pathlib import Path

HOOKS_PATH = Path.home() / ".claude" / "hooks.yaml"

# Named hooks to always remove (duplicates / stale)
REMOVE_IDS = {
    "worktree-on-wt-create-zoxide",  # canonical: zoxide-on-wt-create
    "worktree-on-wt-remove-zoxide",  # canonical: zoxide-on-wt-remove
    "hook-008",
    "hook-009",
    "hook-037",
    "hook-048",  # stale auto-generated
    "hook-047",  # garbage test hook (a → b)
}


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    if not HOOKS_PATH.exists():
        print(f"Not found: {HOOKS_PATH}")
        sys.exit(1)

    data = yaml.safe_load(HOOKS_PATH.read_text(encoding="utf-8"))
    hooks = data.get("hooks", [])
    before = len(hooks)

    kept = []
    removed = []
    for h in hooks:
        hid = h.get("id", "")
        if h.get("source") == "auto" or hid in REMOVE_IDS:
            removed.append(hid)
        else:
            kept.append(h)

    after = len(kept)
    print(f"Hooks before: {before}")
    print(f"Removing {before - after} hooks:")
    for hid in removed:
        print(f"  - {hid}")
    print(f"Hooks after: {after}")

    if dry_run:
        print("\n[dry-run] No changes written.")
        return

    data["hooks"] = kept
    HOOKS_PATH.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print("\nDone. ~/.claude/hooks.yaml updated.")


if __name__ == "__main__":
    main()
