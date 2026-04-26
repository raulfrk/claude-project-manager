# SessionStart Hook Reliability — Design

**Date**: 2026-04-26
**Tracks todos**: 774 (uv-run cold-start), 775 (resolver fork bug)
**Status**: approved (brainstorm); ready for implementation plan

## Problem

The proj plugin's SessionStart hook fails silently on a non-trivial fraction of fresh sessions. Symptom: `proj_session_context` returns `"no active project"` despite SessionStart being configured and the project being tracked. Two independent root causes both produce this same failure mode:

1. **774 — `uv run` cold-start exceeds 10s hook timeout.** `hooks.json` invokes the CLI via `uv --directory ... run python -m server.cli ...` with `timeout: 10`. On cold uv cache (after a `uv` upgrade, plugin reinstall, or extended idle), `uv run` performs lockfile resolution + venv hydration that can exceed 60s. Claude Code kills the hook silently; user gets no project context loaded and no error.

2. **775 — Session-key resolver picks the wrong (transient) Claude pid.** Claude Code forks itself before exec'ing hook commands. Process tree under SessionStart:
   ```
   claude-bin (OUTER, long-lived, parents MCP servers)
    └─ claude-bin (INNER, transient fork for hook execution)
        └─ <shell or interpreter chain>
            └─ python (cli.py)
   ```
   The resolver at `plugins/_shared/session_key/session_key.py:60-63` returns the **first** ancestor whose exe matches `CLAUDE_CODE_EXECPATH`. From the hook's perspective, that's INNER. MCP servers, spawned directly by OUTER, resolve via the fast path (`os.getppid()`) to OUTER. Hook writes `proj-session.yaml` keyed by INNER; MCP servers read it keyed by OUTER. The two pids never agree.

Both bugs surface as the same user-visible symptom. They are independently rootable but share a symptom and a fix-shipping cadence, so this design treats them as one combined fix.

## Goal

SessionStart, SessionEnd, and PreCompact hooks reliably load/refresh project context within their configured `timeout: 10`, regardless of:
- Cold uv cache (post-upgrade, post-reinstall, post-idle).
- Claude Code's self-fork for hook execution.

After the fix, `proj_session_context` returns the active project on the first call after session start, every time, with no env-var workarounds, marker files, or per-deployment tuning.

## Non-goals

1. **Other plugins' hook timeouts** — only `plugins/proj/hooks/hooks.json` is touched. Sweeps for `wiki`, `router`, etc. are separate todos if they hit the same trap.
2. **Installer changes** — installer already creates `.venv/` post-`uv sync`. We rely on that contract; no installer-side repair logic is added.
3. **Hook timeout policy refactor** — `timeout: 10` stays. Direct venv-python cold-start measured ~3.8s; not raising to 30s as defense-in-depth.
4. **Marker-file or env-var session-key fallback** — resolver stays purely process-tree-based.
5. **Claude Code upstream filing** — captured in todo 774's notes as a separate action item; not implemented here.
6. **Dropping `psutil` dependency** — resolver continues to use `psutil` for `parents()` + `pid_exists`.

## Architecture

Two independent code changes, each in a single file:

| Concern | File | Change |
|---|---|---|
| Hook invocation cold-start | `plugins/proj/hooks/hooks.json` | Replace `uv --directory ... run python` w/ direct `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python` for all 3 hooks (SessionStart, SessionEnd, PreCompact). |
| Session-key resolution | `plugins/_shared/session_key/session_key.py` (`get_claude_session_key`) | First-match → outermost-match in ancestor walk. Drop the `os.getppid()` fast path entirely; single resolution path. |

No installer changes. No plugin-manifest changes. No CLI changes. Both hooks and MCP servers continue to import the same shared `session_key` package — fix lands once, applies everywhere.

**End-to-end verification path** (post-fix):
- Hook fires under INNER → CLI walks ancestors → resolves to OUTER (outermost EXECPATH match) → writes `proj-session.yaml` keyed by OUTER.
- MCP server walks ancestors → resolves to OUTER (its only EXECPATH-matching ancestor) → reads `proj-session.yaml` keyed by OUTER.
- Both code paths agree → `proj_session_context` returns the project.

## Component 1: Hook Invocation Path

**File**: `plugins/proj/hooks/hooks.json`

**Change** — all 3 hook entries swap the `command` field:

| Hook | Before | After |
|---|---|---|
| SessionStart | `uv --directory ${CLAUDE_PLUGIN_ROOT}/server run python -m server.cli session-start --cwd "$CLAUDE_PROJECT_DIR"` | `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python -m server.cli session-start --cwd "$CLAUDE_PROJECT_DIR"` |
| SessionEnd | `uv --directory ${CLAUDE_PLUGIN_ROOT}/server run python -m server.cli session-end --cwd "$CLAUDE_PROJECT_DIR"` | `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python -m server.cli session-end --cwd "$CLAUDE_PROJECT_DIR"` |
| PreCompact | `uv --directory ${CLAUDE_PLUGIN_ROOT}/server run python -m server.cli session-start --cwd "$CLAUDE_PROJECT_DIR" --compact` | `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python -m server.cli session-start --cwd "$CLAUDE_PROJECT_DIR" --compact` |

**Other fields unchanged**: `timeout: 10`, `statusMessage`, `async: true` on SessionEnd.

**Performance**: cold-start drops from 60+s to ~3.8s (verified locally). Warm <1s. Plenty of headroom under the 10s timeout.

**Contract w/ installer**: `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python` must exist post-install. Already true today (per shared-venv path: `.venv/` symlinks to shared venv after `uv sync`). If `.venv` is missing → user has a broken install; hook exec fails loud w/ "No such file or directory"; remediation is `cpm-install --reinstall`. No fallback path; no hidden retry.

**Why no PYTHONPATH needed**: `session_key` and other shared deps are already on the venv's `sys.path` via editable installs in `pyproject.toml`. Verified locally per bug 774.

**Why this doesn't break uv-managed dependency upgrades**: `uv sync` still runs at install time. Hook-time invocation skips `uv run`'s lockfile check (the 60s cold-cache cost) but `.venv` is fully hydrated by install, so the python interpreter has all deps. The only thing we lose is auto-resync on manual `pyproject.toml` edits between installs — not a hook-time concern.

## Component 2: Session-Key Resolver

**File**: `plugins/_shared/session_key/session_key.py`
**Function**: `get_claude_session_key()` (lines 30-69)

**New algorithm**:

```python
def get_claude_session_key() -> str:
    """Return the calling process's outermost Claude Code ancestor pid as a string.

    Walks psutil.Process().parents() and returns the OUTERMOST ancestor whose
    exe path matches CLAUDE_CODE_EXECPATH (the env var Claude Code injects into
    every subprocess). Outermost-match — not first-match — because Claude
    self-forks for hook execution; the inner fork is transient and never
    authoritative for session state.

    Falls back to os.getpid() when EXECPATH is unset (tests, non-Claude
    environments) or no ancestor matches.
    """
    expected_raw = os.environ.get("CLAUDE_CODE_EXECPATH", "")
    if not expected_raw:
        return str(os.getpid())
    expected = os.path.realpath(expected_raw)

    last_match: int | None = None
    try:
        for ancestor in psutil.Process().parents():
            try:
                if os.path.realpath(ancestor.exe()) == expected:
                    last_match = ancestor.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass

    if last_match is not None:
        return str(last_match)
    return str(os.getpid())
```

**Diff from current implementation**:
- Removes the `os.getppid()` fast path (lines 49-56 of current file).
- Changes the walk loop from `return str(ancestor.pid)` on first match to assigning `last_match` and continuing.
- Returns `last_match` after the walk; falls back to `os.getpid()` only if `last_match` is `None`.

**Why drop the fast path entirely** (vs. guarding it):
- `psutil.Process().parents()` iteration is microseconds for typical depths (≤10 ancestors). Negligible overhead vs. one `Process(ppid).exe()` call.
- Guard logic ("trust ppid only if grandparent's exe also matches EXECPATH") is non-obvious and itself fragile.
- Single resolution path = simpler mental model, fewer test branches, no asymmetry between hooks vs. MCP servers.

**Why outermost is correct**:
- OUTER = long-lived Claude Code process; parents MCP servers; owns session state.
- INNER = transient fork for hook execution; never authoritative.
- From `cli.py`, `psutil.Process().parents()` yields ancestors in ascending order (immediate parent first, init last): `[shell/interpreter, INNER, OUTER, terminal/launcher, ...]`. Both INNER and OUTER match EXECPATH; the terminal/launcher does not. The walk records both matches and assigns `last_match = OUTER.pid` last — that's the outermost match.
- Multi-session safety: each session's outer process is distinct; ancestor chains don't cross sessions.
- Subagent / `--continue` re-launch: nested sessions resolve to the nearest session boundary (their own outermost in-chain match), correct for owning that session's state.

**Iteration-order assumption**: `psutil.Process().parents()` returns ancestors immediate-first, ascending toward init. The "outermost = last `last_match` written" logic depends on this. The assumption holds across all current psutil versions; if upstream ever inverts the order, the regression test from the test plan (`test_outermost_match_when_multiple_claude_ancestors`) catches the change.

**Edge cases preserved from current implementation**:
- EXECPATH unset → `os.getpid()` fallback.
- No matching ancestor → `os.getpid()` fallback.
- Dead/inaccessible ancestor mid-walk → `continue`, walk the rest.
- Symlinks → `os.path.realpath()` on both sides.

## Testing

### Unit tests

File: `plugins/_shared/tests/test_session_key.py`. Add 3 new test cases to the existing `TestSessionKey` class:

1. **`test_outermost_match_when_multiple_claude_ancestors`** — fork-chain regression test for bug 775. Mocks `psutil.Process().parents()` to return `[bash, python, inner_claude(pid=100), outer_claude(pid=200), launcher(pid=1)]` where `inner_claude.exe()` and `outer_claude.exe()` both resolve to EXECPATH but `launcher.exe()` doesn't. Asserts resolver returns `"200"` (outermost), not `"100"` (first match).

2. **`test_ppid_match_does_not_short_circuit_walk`** — confirms fast path is gone. Mocks `os.getppid()` to return a pid whose exe matches EXECPATH AND a `parents()` chain w/ a deeper match. Asserts the deeper pid wins; ppid match alone no longer short-circuits resolution.

3. **`test_outermost_match_with_dead_pid_in_chain`** — combines fork chain w/ a dead/inaccessible ancestor mid-walk. Asserts `continue`-on-error doesn't short-circuit the walk; outermost live match still wins.

### Existing tests audit

- **`test_direct_parent_match_returns_ppid`** (line 63 of current test file) — semantics shift: it currently asserts ppid is returned via the fast path. After the fix, ppid is still returned because `parents()` would yield only that one matching ancestor. Update mock setup to use `parents()` instead of relying on the fast path. Test name + assertion stay valid.
- **`test_mid_chain_ancestor_match`** (line 78) — still valid; outermost-match returns the same single match when only one ancestor matches.
- **`test_no_ancestor_matches_falls_back_to_own_pid`** (line 101) — unchanged.
- **`test_no_such_process_mid_walk_continues`** (line 121) — unchanged.
- **`test_realpath_normalization`** (line 143) — unchanged.

### Hook config — no automated test

The `hooks.json` change is config; testing it would require spawning Claude Code, which is out of scope. Manual smoke instead.

### Manual smoke (post-merge, on user's host)

1. `cd plugins/proj/server && rm -rf .venv && uv sync` (rehydrate to mimic post-install state).
2. Optionally: `uv cache clean` (mimic cold cache; only needed if curious about the 60s baseline).
3. Start a fresh Claude Code session in `~/projects/claude-project-manager/`.
4. Verify:
   - Hook completes within ~4s (no `[hook timed out]` in session log).
   - `proj_session_context` returns active project name (not "no active project").
   - `~/.claude/proj-session.yaml` key matches `pgrep -af claude-bin` outermost pid.
5. Repeat in a second concurrent Claude session → verify keys differ + don't clobber.

### Coverage

Existing `_shared` package coverage threshold (basedpyright + ruff + pytest pre-commit) must hold. New tests must keep coverage ≥ current; no new uncovered branches.

## Risks Accepted

- **`.venv` missing during partial install** — hook fails until `cpm-install --reinstall`. No silent fallback. Tradeoff: simpler config, fewer code paths, loud failures over hidden ones.
- **Fast-path removal microcost** — every MCP server resolves via `parents()` instead of a single `Process(ppid).exe()` call. Microseconds-scale; well below the noise floor of any operation that calls it.

## Out-of-scope follow-ups

- **Sweep other plugins** for the same `uv run` cold-start trap (wiki, router, todoist, jira, trello, confluence, zoxide). Tracked separately if any are affected.
- **File the upstream issue** referenced in todo 774's notes — separate action; once we ship the local fix, less urgent for our case but useful for downstream plugins.
