# 683 Follow-ups — Design

**Todos**: 693, 694
**Date**: 2026-04-21
**Status**: draft (brainstorming)

## Problem

Two small follow-ups auto-captured during the `--local-marketplace` feature work:

- **693**: A code reviewer reported pre-existing installer test failures involving `claudemd` imports. Investigation showed the failures only occur when `uv run pytest` runs without the test group sync'd (`uv sync --group test` or `uv sync --all-groups`). CI uses the correct invocation and is green on current dev (`f8f1ad6`). Not a code bug — a developer-setup gap.
- **694**: `installer/plugin_cli.py` declares `_MARKETPLACE_SOURCE` and `_MARKETPLACE_NAME` with leading underscores (module-private by convention), but external callers — `installer/main.py`, test modules, and the 683 design docs — import them directly. Convention violation; rename to public.

## Solution

Two disjoint changes, bundled in one spec/plan/PR:

1. **693**: Add a short "Before running tests" note in `docs/development.md` under the existing `## Running Tests` section. Close todo 693 as documentation-only.
2. **694**: Rename `_MARKETPLACE_SOURCE` → `MARKETPLACE_SOURCE` and `_MARKETPLACE_NAME` → `MARKETPLACE_NAME`. Atomic single-commit rename across source, tests, and design docs. Close todo 694.

No behavior changes. No new features. TDD where applicable (full suite green pre-rename and post-rename).

## Scope

### In scope

- `docs/development.md` — one new block, ~4 lines.
- `installer/plugin_cli.py` — 2 constant declarations + 6 default-param references.
- `installer/main.py` — 1 import + 1 reference.
- `installer/tests/test_main.py` — 1 import + 6 references.
- `installer/tests/test_plugin_cli.py` — 2 imports + ~22 references (the majority, mostly `_MARKETPLACE_NAME` string-interpolation into plugin IDs like `f"proj@{_MARKETPLACE_NAME}"`).
- `docs/superpowers/specs/2026-04-21-installer-local-marketplace-design.md` — 4 references.
- `docs/superpowers/plans/2026-04-21-installer-local-marketplace.md` — 5 references.

### Out of scope

- Changing the hardcoded constant values (`"raulfrk/claude-project-manager"` stays the same).
- Touching `plugin_cli.py`'s other module-private names (`_TIMEOUT`, `_run`, `_MARKETPLACE_*` are the only underscores used).
- Modifying CI configuration or adding pre-commit hooks to detect the 693-class misuse.
- Adding alias shims for backward-compatibility (internal code, hard-rename is fine).

## Architecture

### 693 — Documentation note

Add a subsection to `docs/development.md` under `## Running Tests` (existing section at line 102). Content:

```markdown
### Before running tests

Local tests require the `test` dependency group to be installed. Run
`just sync` (which runs `uv sync --all-groups` across every plugin and
the installer) once after a fresh checkout. The canonical local
workflow is:

    just sync   # installs deps including the `test` group
    just test   # runs pytest across all plugins + installer

Running `uv run pytest` directly without syncing the `test` group first
results in collection errors (missing `claudemd` module) because that
module lives in the `plugins/_shared` package, which is installed as a
dev dependency.
```

The existing "Running Tests" section already documents per-plugin invocations; this sits above those as a prerequisite.

### 694 — Rename constants

In `installer/plugin_cli.py`:

```diff
-_MARKETPLACE_NAME = "claude-project-manager"
-_MARKETPLACE_SOURCE = "raulfrk/claude-project-manager"
+MARKETPLACE_NAME = "claude-project-manager"
+MARKETPLACE_SOURCE = "raulfrk/claude-project-manager"
```

Default-parameter references in the same file (6 occurrences across `check_marketplace_registered`, `add_marketplace`, `remove_marketplace`, `get_installed_plugins`, `get_installed_plugin_versions`, `get_available_plugins`) update mechanically.

Importers:

```diff
 # installer/main.py
-from installer.plugin_cli import _MARKETPLACE_SOURCE
+from installer.plugin_cli import MARKETPLACE_SOURCE

 def _resolve_marketplace_source(args) -> tuple[str, str | None]:
     ...
-    return (_MARKETPLACE_SOURCE, getattr(args, "branch", None))
+    return (MARKETPLACE_SOURCE, getattr(args, "branch", None))
```

Tests update the same way — import the new names, use the new names in assertions and fixture strings.

## Execution order

1. Apply all source-code renames in one commit. Run the full test suite. Tests must be green before committing.
2. Apply all doc-file renames in a second commit. No tests needed; just verify the files still render as markdown.
3. Add the 693 `docs/development.md` note in a third commit.

Splitting the three concerns across three commits makes each reviewable on its own; squashing is optional at merge time.

## Testing

- **694**: After the rename, run `just sync && just test` (or the equivalent `uv run --group test python -m pytest installer/tests -v`). Expect 666/666 pass. No new test code needed — existing tests already reference the symbols by name.
- **693**: No automated test. Manual verification: `uv run pytest installer/tests` from a fresh checkout fails with a missing-module error, then `just sync` followed by `uv run pytest installer/tests` passes. The doc note is sufficient guidance.

## Out-of-scope follow-ups (informational)

- Adding a `conftest.py` hook that detects the "test group not installed" state and prints an actionable error — defensive but higher effort. Not pursued here per user decision.
- Sweeping the broader codebase for other underscore-prefixed constants imported externally (e.g. `plugin_cli._TIMEOUT`, if ever imported elsewhere). Not required for this spec.
