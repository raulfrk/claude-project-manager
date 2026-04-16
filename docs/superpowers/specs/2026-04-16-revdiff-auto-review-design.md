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

### Component 1a — Extract `MANAGED_SECTION` body to a content file

**New file**: `installer/managed_section.md`

Today the section body is a multiline `f"""..."""` literal inside `installer/claudemd.py`. Extract the full section (markers + heading + all bullets) into a standalone Markdown file that the Python side reads at module load. This makes content edits diff-friendly, unblocks non-Python contributors from updating rules, and decouples content churn from code churn.

**New file contents** (verbatim): the current `MANAGED_SECTION` string, including the `<!-- claude-project-manager:start -->` / `<!-- claude-project-manager:end -->` marker lines at top/bottom.

**`installer/claudemd.py` change**: replace the string literal with a module-level load:

```python
_SECTION_PATH = Path(__file__).parent / "managed_section.md"
MANAGED_SECTION = _SECTION_PATH.read_text(encoding="utf-8").rstrip("\n")
```

`MARKER_START` / `MARKER_END` remain as constants — `remove_managed_section` and `_has_both_markers` still use them for splitter logic, and the same marker strings happen to be the first/last lines of `managed_section.md`.

**Packaging**: the `.md` file must ship with the `installer` package. Verify `pyproject.toml` (or equivalent) includes `*.md` in package data; add if missing. The plan phase will inspect the current packaging config and add one explicit step to update it if needed.

**Failure mode**: if `managed_section.md` is missing at runtime (e.g. broken install), module import raises `FileNotFoundError`. That is the correct behavior — a broken install should fail loudly, not silently write an empty managed block.

### Component 1b — Append the revdiff bullet

Add the following bullet to the end of the bullet list inside `installer/managed_section.md`:

> - **Revdiff-routed spec/plan review** — When a superpowers skill produces a spec/plan/design file and reaches the "ask user to review" step, check if revdiff is available: `enabledPlugins["revdiff@revdiff"] == true` in `~/.claude/settings.json` AND `which revdiff` returns 0. If both hold, invoke the `revdiff:revdiff` skill on the file instead of asking the user to read it manually. If either check fails, fall back silently to the skill's default text-review prompt. This rule applies only to superpowers skills; skills outside the superpowers namespace are unaffected.

The bullet is phrased as a procedural directive to Claude — same style as the existing "Auto-capture issues as todos" and "Interactive Q&A" bullets. No config flag, no per-skill override; the rule is unconditional except for the revdiff-available gate.

### Component 2a — New MCP tool: `claudemd_refresh_managed`

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

**Import note**: the `installer` package must be importable from the proj server. If it is not already a runtime dependency, either (a) add it to the proj server's deps, or (b) copy the small `ensure_managed_section` + constants into a shared location. The plan phase will pick one after verifying current import topology. Note: whichever path is chosen, the content lives in `installer/managed_section.md` per Component 1a — both the installer and the refresh tool must resolve to that same file so they never drift.

### Component 2b — New skill: `/proj:claudemd-refresh`

**New file**: `plugins/proj/skills/claudemd-refresh/SKILL.md`

User-invocable slash command wrapping the MCP tool from Component 2a. Discoverable via the `/proj:` prefix; users do not need to remember the MCP tool name.

**Naming**: `/proj:claudemd-refresh` — noun-verb pattern consistent with the existing sync family (`/proj:jira-sync`, `/proj:trello-sync`, `/proj:todoist-sync`). Refreshing the managed block is operationally the same shape as those syncs: pull the latest canonical state into a local file.

**Content**: caveman ultra per project conventions. Concise SKILL.md:
- Frontmatter with `name`, `description`, `context: fork`, `agent: general-purpose` (self-contained, non-interactive).
- Single step: call `mcp__proj__claudemd_refresh_managed`.
- Report back to user: `updated` boolean + `path`. If `updated=True`: "Managed block refreshed at `<path>`." If `updated=False`: "Managed block already current at `<path>`."

**Plugin registration**: add the skill to the proj plugin's skills index (README skill reference table + skills-by-category list per project CLAUDE.md convention). No MCP server changes — skill calls the tool registered in Component 2a.

### Component 3 — Tests

**File**: `installer/tests/test_claudemd.py` (existing)

Three tests:

1. `test_managed_section_loaded_from_file` — assert `MANAGED_SECTION` equals `managed_section.md` content with the trailing newline trimmed, and that markers are the first and last lines of the file.
2. `test_managed_section_contains_revdiff_rule` — cheap regression guard on the new bullet:
   ```python
   assert "Revdiff-routed spec/plan review" in MANAGED_SECTION
   assert 'enabledPlugins["revdiff@revdiff"]' in MANAGED_SECTION
   ```
3. `test_managed_section_file_shipped` — packaging check. Import the installer package and assert `(Path(installer.__file__).parent / "managed_section.md").is_file()`. This guards against the `.md` being stripped by a future packaging refactor.

**File**: `plugins/proj/server/tests/test_context.py` (existing)

Tests for `claudemd_refresh_managed`:

1. Fresh file case: file does not exist → tool call creates it → returns `{"updated": True, ...}` → file contains markers + section body.
2. Already-current case: file contains current section → tool call returns `{"updated": False, ...}` → file unchanged.
3. Stale-section case: file contains markers with old content → tool call returns `{"updated": True, ...}` → file contains the current section body between the markers, preserving surrounding content.

Use `tmp_path` + monkeypatch of `Path.home()` to avoid touching the real `~/.claude/CLAUDE.md`.

**Skill-level verification** (manual, not automated): confirm `/proj:claudemd-refresh` appears in the `/proj:` skill listing and invoking it on a stale CLAUDE.md updates the block.

### Component 4 — Documentation touch-ups

- `installer/claudemd.py` — update any docstring summary of `MANAGED_SECTION` to note the content lives in `managed_section.md`.
- `README.md` — if it documents the managed block bullets, add the new revdiff bullet to that list, and add `/proj:claudemd-refresh` to the skills table + skills-by-category list.

These are non-optional for this change set — the skills table is the canonical discovery surface, and the README's managed-block list needs to stay in sync with the content file.

## Data Flow

```
+---------------------------------+
| installer/managed_section.md    |   (single source of truth for content)
+---------------------------------+
           |
           | read at module load
           v
+---------------------------------+
| installer/claudemd.py           |
|   MANAGED_SECTION constant      |
|   ensure_managed_section()      |
+---------------------------------+
           |                \
 (1) wizard/installer runs   \  (2a) MCP tool: claudemd_refresh_managed
           |                  \      (2b) Skill: /proj:claudemd-refresh  ---> calls 2a
           v                   v
  +------------------------------------+
  |   ~/.claude/CLAUDE.md              |
  |   (managed block w/ revdiff rule)  |
  +------------------------------------+
           |
 (3) rule loaded into Claude ctx
           v
+----------------------------------------+
| Superpowers skill reaches              |
| "ask user to review" step              |
+-------------------+--------------------+
                    |
                    v
+----------------------------------------+
| Claude checks:                         |
| - settings.json                        |
|   enabledPlugins["revdiff@revdiff"]    |
|   == true?                             |
| - `which revdiff` == 0?                |
+-------------------+--------------------+
                    |
   yes to both      |       either fails
 +------------+     |     +--------------+
 | Invoke     |<----+---->| Default text |
 | revdiff    |           | "please      |
 | skill on   |           | review"      |
 | the file   |           | prompt       |
 +------------+           +--------------+
```

## Alternatives Considered

### Keep `MANAGED_SECTION` as a Python string literal
Current state: the section body is inlined in `installer/claudemd.py` as an f-string.
**Rejected** — content changes churn the Python file; diffs mix logic and prose; non-Python contributors have to edit Python source to tweak a bullet. Extracting to `managed_section.md` isolates the content surface.

### MCP tool only, no slash-command skill
Ship `claudemd_refresh_managed` without `/proj:claudemd-refresh`.
**Rejected** — users have to remember the raw tool name; not discoverable via the `/proj:` prefix; inconsistent with the other ops shortcuts (`/proj:jira-sync`, `/proj:trello-sync`, `/proj:todoist-sync`).

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

1. `installer/managed_section.md` exists and contains the full managed section (markers + heading + bullets including the new revdiff bullet).
2. `installer/claudemd.py` no longer contains the section body as a Python string literal — `MANAGED_SECTION` is loaded from `managed_section.md` at module load time.
3. Packaging config ships `installer/managed_section.md` with the installer package.
4. `claudemd_refresh_managed` MCP tool is registered on the proj server and returns `{updated, path}` as specified.
5. `/proj:claudemd-refresh` skill exists at `plugins/proj/skills/claudemd-refresh/SKILL.md`, is listed in the README skills table and skills-by-category list, and invoking it calls the Component 2a tool and reports the result.
6. All listed tests pass on CI (content-file load test, revdiff-bullet regression guard, packaging check, refresh-tool unit tests).
7. Manual verification: installer wizard on a clean `~/.claude` produces a CLAUDE.md containing the new bullet; running `/proj:claudemd-refresh` on a stale block updates it in place.

## Open Questions

- Should the bullet name the two current target skills (`brainstorming`, `writing-plans`) explicitly as examples, or stay fully generic? The approved scope is "anything superpowers-related", so the current wording stays generic — but the plan phase may choose to append a parenthetical "(e.g. brainstorming, writing-plans)" for clarity. Not a blocker either way.
