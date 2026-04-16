# Revdiff-Routed Spec/Plan Review — Design

**Date**: 2026-04-16
**Todo**: 639 — "Managed CLAUDE.md: auto-ask user to review plan/spec via revdiff when revdiff enabled"
**Status**: approved, awaiting implementation plan
**Priority**: low

## Problem

Superpowers workflow skills that produce a spec, plan, or design file (notably `superpowers:brainstorming` and `superpowers:writing-plans`; future candidates include any further superpowers skills that emit a reviewable artifact) currently ask the user to read the file manually: *"Please review it and let me know if you want changes."*

When the `revdiff` skill is installed and enabled, the same review would be dramatically better as an interactive TUI overlay with inline annotations. Today there is no cross-skill mechanism to route the review step through revdiff — each skill hardcodes its own "please review" prompt.

## Goals

- When Claude reaches a "user reviews the artifact" step inside a **superpowers** skill that produced a spec/plan/design file, and revdiff is actually usable, Claude invokes the `revdiff:revdiff` skill on that file instead of the default text prompt.
- Rule lives in one place — the global CLAUDE.md managed block — rather than forking upstream superpowers skills.
- Detection is dynamic: the rule reflects the current state of the user's plugin install at the moment the review step is reached, not stale install-time bookkeeping.
- If revdiff is not usable, nothing changes: the skill's existing text-review prompt runs silently.

## Non-Goals

- No changes to superpowers skills themselves. The rule lives in CLAUDE.md; Claude follows it at skill-execution time.
- No per-project CLAUDE.md managed block. The injector continues to target only `~/.claude/CLAUDE.md`.
- No runtime detection caching. Claude rechecks each time it reaches a review step.
- No telemetry or logging of whether revdiff was routed.
- No guarantee for non-superpowers skills. The rule's scope is explicit: superpowers only.
- No behavior change for artifacts that are not spec/plan/design files (e.g. code changes, notes, todo mutations).

## Design

### Component 1 — New bullet in `MANAGED_SECTION`

**File**: `installer/claudemd.py`

Add one bullet (appended at the end of the existing list in the `MANAGED_SECTION` string constant) with the following text:

> - **Revdiff-routed spec/plan review** — When a superpowers skill produces a spec/plan/design file and reaches the "ask user to review" step, check if revdiff is available: `enabledPlugins["revdiff@revdiff"] == true` in `~/.claude/settings.json` AND `which revdiff` returns 0. If both hold, invoke the `revdiff:revdiff` skill on the file instead of asking the user to read it manually. If either check fails, fall back silently to the skill's default text-review prompt. This rule applies only to superpowers skills; skills outside the superpowers namespace are unaffected.

The bullet is phrased as a procedural directive to Claude — same style as the existing "Auto-capture issues as todos" and "Interactive Q&A" bullets. No config flag, no per-skill override; the rule is unconditional except for the revdiff-available gate.

### Component 2 — New MCP tool: `claudemd_refresh_managed`

**File**: `plugins/proj/server/server/tools/context.py`

Expose `ensure_managed_section` via a new MCP tool so existing users can refresh their managed block without re-running the full installer/wizard.

**Signature**:

```python
@app.tool(description="Refresh the cpm-managed section in ~/.claude/CLAUDE.md to the current version.")
def claudemd_refresh_managed() -> dict:
    ...
```

**Behavior**:
- Resolves `~/.claude/CLAUDE.md` via `Path.home()`.
- Calls `ensure_managed_section(path)` from `installer.claudemd`.
- Returns `{"updated": bool, "path": str}` where `updated` is the function's return value (True = file modified, False = already current).

**Error handling**:
- If `~/.claude/CLAUDE.md`'s parent directory is missing, `ensure_managed_section` already handles it (`parent.mkdir(parents=True, exist_ok=True)` in `_atomic_write`).
- If the file is unreadable (permission error), let the exception propagate — this is a configuration problem the user should see directly, not swallow.

**Import note**: the `installer` package must be importable from the proj server. If it is not already a runtime dependency, either (a) add it to the proj server's deps, or (b) copy the small `ensure_managed_section` + constants into a shared location. The plan phase will pick one after verifying current import topology.

### Component 3 — Tests

**File**: `installer/tests/test_claudemd.py` (existing)

Add a test that asserts the new revdiff bullet is present in `MANAGED_SECTION`. This is a cheap regression guard — if someone refactors the bullet away accidentally, the test fails.

```python
def test_managed_section_contains_revdiff_rule():
    assert "Revdiff-routed spec/plan review" in MANAGED_SECTION
    assert 'enabledPlugins["revdiff@revdiff"]' in MANAGED_SECTION
```

**File**: `plugins/proj/server/tests/test_context.py` (existing)

Add a test for `claudemd_refresh_managed`:

1. Fresh file case: file does not exist → tool call creates it → returns `{"updated": True, ...}` → file contains markers + section body.
2. Already-current case: file contains current section → tool call returns `{"updated": False, ...}` → file unchanged.
3. Stale-section case: file contains markers with old content → tool call returns `{"updated": True, ...}` → file contains the current section body between the markers, preserving surrounding content.

Use `tmp_path` + monkeypatch of `Path.home()` to avoid touching the real `~/.claude/CLAUDE.md`.

### Component 4 — Documentation touch-ups (optional)

- If `installer/claudemd.py` has a docstring summary of what `MANAGED_SECTION` contains, update it to mention the new rule.
- If `README.md` documents the managed block bullets, add the new rule to that list.

These are non-blocking; the plan will include them if the files already describe the managed block inventory.

## Data Flow

```
+----------------------------+      (1) wizard runs
| installer/claudemd.py      |---------------+
|  ensure_managed_section()  |               |
+----------------------------+               v
                                  +--------------------------+
(2) existing user runs new tool   | ~/.claude/CLAUDE.md      |
+----------------------------+    |  (managed block with     |
| claudemd_refresh_managed   |--->|   revdiff rule bullet)   |
|  (proj MCP tool)           |    +--------------------------+
+----------------------------+               |
                                  (3) rule loaded into Claude ctx
                                             |
                                             v
                               +------------------------------+
                               | Superpowers skill reaches    |
                               | "ask user to review" step    |
                               +---------------+--------------+
                                               |
                                               v
                               +------------------------------+
                               | Claude checks:               |
                               | - settings.json              |
                               |   enabledPlugins["revdiff@   |
                               |   revdiff"] == true?         |
                               | - `which revdiff` == 0?      |
                               +---------------+--------------+
                                               |
                       yes to both             |            either fails
              +------------------+             |          +-------------------+
              | Invoke revdiff:  |<------------+--------->| Default text      |
              | revdiff skill    |                        | "please review"   |
              | on the file      |                        | prompt            |
              +------------------+                        +-------------------+
```

## Alternatives Considered

### Per-skill fork
Edit `brainstorming/SKILL.md` and `writing-plans/SKILL.md` in the cached superpowers plugin.
**Rejected** — plugin updates overwrite edits; only covers two skills; doesn't generalize to future superpowers skills.

### Per-project managed block
Extend the injector to maintain a managed section inside each project's repo CLAUDE.md.
**Rejected** — larger change; scope is a global workflow rule, not project-specific.

### New shim skill `/proj:revdiff-review` invoked from others
Create a sub-skill that other skills call.
**Rejected** — still requires editing the calling skills; same fragility as the fork option.

### proj.yaml flag (`revdiff.auto_review: true`)
User opts in explicitly via config.
**Rejected** — adds config surface; dynamic detection of the revdiff plugin already gives the right default ("on if installed") with no extra user action.

### Auto-refresh on `proj_load_session`
Hook that runs `ensure_managed_section` on every project load.
**Rejected** — surprising side effect; potential conflict with user hand-edits to `~/.claude/CLAUDE.md`; refresh is a rare operation, not a per-load one.

### Static detection baked at install time
Wizard injects the rule only if revdiff is enabled at that moment.
**Rejected** — stale if user enables revdiff later; forces users to re-run wizard on plugin state changes.

## Risks and Edge Cases

- **Stale rule text after upgrade** — users who updated cpm without re-running the wizard keep the old `MANAGED_SECTION`. Component 2 (`claudemd_refresh_managed`) provides the remediation path; document it in the changelog for the version that ships this change.
- **User has hand-edited the managed block** — the injector is a full-section replace between markers, so hand-edits to the managed block are lost on refresh. This is the existing contract of the managed-block system and is not changed by this design; mention in the release notes.
- **`which revdiff` on systems without the binary** — the rule text says "returns 0", which Claude interprets as "the binary exists on PATH". If revdiff is enabled in `enabledPlugins` but the binary is not installed, the rule falls back silently — correct.
- **`settings.json` malformed** — if Claude cannot parse `enabledPlugins`, it treats the check as failed and falls back. The rule text does not need to specify this; standard LLM error handling applies.
- **Artifact path uncertainty** — the review step always has a known file path at the moment it runs (the skill just wrote the file). The rule delegates "which file" to the calling skill's context.

## Testing Strategy

- `test_managed_section_contains_revdiff_rule` — regression guard on the bullet text.
- `test_claudemd_refresh_managed_fresh` — file creation path.
- `test_claudemd_refresh_managed_noop` — idempotence when already current.
- `test_claudemd_refresh_managed_updates_stale` — in-place replacement between markers.
- Manual verification: run the installer/wizard on a clean `~/.claude/CLAUDE.md`, confirm the new bullet is present. Separately, call the new MCP tool on a file with an old `MANAGED_SECTION` and confirm the bullet is added.

End-to-end verification of the rule itself (i.e. Claude actually routing to revdiff during a brainstorming session) is out of scope for automated tests — it depends on LLM behavior against the rule text. Acceptance criterion: in a live session with revdiff installed, running `superpowers:brainstorming` through to the spec-review step results in a revdiff invocation rather than a text "please review" prompt.

## Acceptance Criteria

1. `MANAGED_SECTION` in `installer/claudemd.py` contains the revdiff bullet with the specified detection logic (settings.json + `which revdiff`) and fallback behavior.
2. `claudemd_refresh_managed` MCP tool is registered on the proj server and returns `{updated, path}` as specified.
3. All listed tests pass on CI.
4. Manual verification: installer wizard on a clean `~/.claude` produces a CLAUDE.md containing the new bullet; the refresh tool updates an existing stale block in place.

## Open Questions

- Should the bullet name the two current target skills (`brainstorming`, `writing-plans`) explicitly as examples, or stay fully generic? The approved scope is "anything superpowers-related", so the current wording stays generic — but the plan phase may choose to append a parenthetical "(e.g. brainstorming, writing-plans)" for clarity. Not a blocker either way.
