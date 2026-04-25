# Session-Key Resolver: Eliminate Cmdline-Regex + Marker Files

**Date**: 2026-04-25
**Status**: design
**Owner**: claude-project-manager
**Tracking todo**: 754

## Problem

`get_claude_session_key()` in `plugins/_shared/session_key/session_key.py` resolves the calling
process's Claude Code ancestor pid via a fragile two-stage chain:

1. **Marker files** at `~/.claude/proj-session-markers/<pid>.yaml` — written by the proj
   plugin's SessionStart hook.
2. **Cmdline regex** matching `(?:^|/)claude(?:-code)?(?:\s|$)` against ancestor cmdlines.

Both stages have defects (todo 754):

- The regex hardcodes binary names (`claude`, `claude-code`) and silently breaks on variants
  like `claude-bin`. It also matches against unstable cmdline argv (varies with
  `--append-system-prompt`, sandbox wrappers, etc.). Per-deployment overrides via
  `CPM_CLAUDE_CODE_CMDLINE_MATCHER` are required.
- The hook calls `write_session_marker(claude_pid=os.getppid(), …)` *before* invoking
  `set_session_active() → get_claude_session_key()`. The marker is keyed by `os.getppid()` —
  the **uv** interpreter's pid (not Claude's), since the hook runs through
  `claude-bin → bash → uv → python cli.py`. Then the resolver's marker check at
  `session_key.py:122-125` finds uv's pid in both `marker_pids` and the ancestor chain →
  returns uv's pid → YAML keyed by uv's (soon-dead) pid → MCP servers later resolve to
  Claude's actual pid → key mismatch → lookup miss.

A regex broadening alone fixes only the read path; the marker self-match still poisons the
write path. Layering surface fixes leaves the architectural fragility (binary-name guessing
+ marker dir + self-match heuristic) intact.

## Approach

Replace the entire resolver with a candidate-free design that uses the
`CLAUDE_CODE_EXECPATH` environment variable Claude Code injects into every subprocess. No
binary-name regex, no marker files, no NS-inode tracking.

```python
def get_claude_session_key() -> str:
    """Resolve the calling process's Claude Code ancestor pid.

    Uses the CLAUDE_CODE_EXECPATH env var (set by Claude Code in every
    subprocess) to identify the Claude binary by canonical exe path —
    no cmdline-regex guessing, no marker files.
    """
    expected = os.path.realpath(os.environ.get("CLAUDE_CODE_EXECPATH", ""))
    if expected:
        # Fast path: direct parent (covers MCP servers spawned by Claude)
        try:
            ppid = os.getppid()
            if os.path.realpath(psutil.Process(ppid).exe()) == expected:
                return str(ppid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        # General path: walk ancestors (covers hooks via bash/uv/etc.)
        try:
            for ancestor in psutil.Process().parents():
                try:
                    if os.path.realpath(ancestor.exe()) == expected:
                        return str(ancestor.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    # Fallback: tests / non-Claude / EXECPATH absent
    return str(os.getpid())
```

Two stages, both probing the same canonical-exe-path identity check:

- **Fast path**: `os.getppid()` exe matches `CLAUDE_CODE_EXECPATH`. Covers stdio MCP servers
  (Claude Code spawns them as direct children).
- **General path**: walk `psutil.Process().parents()`, return the first whose
  `psutil.Process.exe()` realpath matches. Covers hook subprocesses where intermediate
  interpreters (uv, npx, bash) are interposed.

Both stages fall back to `os.getpid()` (same fallback today's resolver uses) when
`CLAUDE_CODE_EXECPATH` is absent — preserves test/non-Claude behavior.

### Why this is correct

- **No hardcoded names**: Claude Code self-identifies via `CLAUDE_CODE_EXECPATH`; resolver
  matches against whatever Anthropic shipped. Forward-compatible to any future binary rename.
- **Survives interpreter interposition**: `uv`, `npx`, `sh -c`, `sudo`, `systemd-run`, etc.
  are skipped because their exe path doesn't match. Only the actual Claude binary matches.
- **Multi-session safe**: Each subprocess has exactly one ancestor chain; a hook under
  `claude-bin` A can never walk into B's territory.
- **Nested sessions (subagents) safe**: Returns the nearest `claude-bin` (first ancestor
  match), which is the correct scope.
- **No write/read race**: with no marker file, there's no intermediate artifact and no
  self-match heuristic. Both hooks AND MCP servers resolve to the same pid via the same
  canonical exe-path check.
- **Sandbox safe**: bwrap/systemd-run/PID-NS preserve `CLAUDE_CODE_EXECPATH` in inherited
  env and `psutil.parents()` walk stops at the in-NS PID 1, so cross-NS leakage is
  impossible without explicit NS-inode tracking.

### Empirical validation (per todo 754)

Linux, `claude-bin` spawned via tmux + `claude-safe` sandbox + `systemd-run`, with `uv`
interposed in hook chain. Direct ppid (MCP) AND ancestor-walk-via-EXECPATH (hook) both
returned `claude-bin`'s pid correctly. Today's regex matcher returned the wrong pid (or no
match) in the same scenarios.

## Files modified

| File | Change |
|------|--------|
| `plugins/_shared/session_key/session_key.py` | Rewrite `get_claude_session_key()`. Delete: `_DEFAULT_MATCHER`, `_get_matcher`, `_cmdline_str`, `_ancestor_pids`, `_read_marker_pids`, `_gc_marker_dir`, `_read_pid_ns_inode`, `write_session_marker`, `remove_session_marker`, `_MARKER_DIR`, `CPM_CLAUDE_CODE_CMDLINE_MATCHER` env handling. Keep: `read_active`, `write_active`, `clear_active`, helpers (`_load_raw`, `_migrate_if_needed`, `_now_iso`, `_atomic_write`, `_gc_dead_pids`). Add one-shot legacy marker dir cleanup inside `write_active`. |
| `plugins/proj/server/server/cli.py` | Drop import of `write_session_marker` / `remove_session_marker` (line 16). Drop `write_session_marker(claude_pid=os.getppid(), cwd=cwd)` call (line 193). Drop `remove_session_marker(claude_pid=os.getppid())` call (line 266). |
| `plugins/_shared/tests/test_session_key.py` (or wherever the test file currently lives — verify path during T0) | Replace marker- and regex-based tests with EXECPATH resolver tests. Keep `read_active` / `write_active` / `clear_active` tests unchanged. |
| `plugins/proj/server/server/tests/test_cli.py` (if present) | Drop any tests that assert `cmd_session_start` writes a marker / `cmd_session_end` removes one. |

## Migration

One-shot cleanup of `~/.claude/proj-session-markers/` on first `write_active` call after
upgrade:

```python
_LEGACY_MARKER_DIR = Path.home() / ".claude" / "proj-session-markers"

def _cleanup_legacy_marker_dir_once() -> None:
    """Best-effort removal of the v1 marker dir. Silently ignores failures."""
    if _LEGACY_MARKER_DIR.is_dir():
        with suppress(OSError):
            shutil.rmtree(_LEGACY_MARKER_DIR)
```

Called inside `write_active` once per process (guarded by a module-level boolean). Silent —
user doesn't need to act. No on-disk schema changes.

## Tests

### `test_session_key.py` rewrite

Replace marker- and regex-based tests with focused unit tests on the new resolver:

| Case | Setup | Assert |
|------|-------|--------|
| EXECPATH unset | `monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)` | returns `str(os.getpid())` |
| Direct parent matches | mock `os.getppid()`, `psutil.Process(ppid).exe()` returns EXECPATH | returns ppid as str |
| Direct parent mismatch, ancestor 2 hops up matches | mock `psutil.Process().parents()` chain w/ exe-path attrs | returns matching ancestor pid |
| No ancestor matches | parents chain has no exe match | returns `str(os.getpid())` |
| `psutil.NoSuchProcess` mid-walk | one ancestor raises | walk continues, finds next match or falls back |
| Legacy marker dir cleanup runs once | `write_active` called twice | `shutil.rmtree(_LEGACY_MARKER_DIR)` invoked once |

Drop entirely:

- `test_*marker*` (marker dir tests)
- `test_*matcher*` / `test_*regex*` / `test_*cmdline*` (matcher tests)
- `test_*ns_inode*` (namespace inode tests, if present)

Keep unchanged:

- `read_active` / `write_active` / `clear_active` round-trip tests
- v1 → v2 migration tests
- `_gc_dead_pids` tests

### Integration smoke (optional, marked `@pytest.mark.slow`)

Spawn a 3-deep subprocess chain (`bash → uv → python -c "from session_key import get_claude_session_key; print(get_claude_session_key())"`) with `CLAUDE_CODE_EXECPATH` set to the test runner's exe. Assert the resolver returns the test runner's pid (the topmost ancestor matching EXECPATH). Verifies multi-hop walk under real OS process semantics.

## Verification

1. `uv run --no-sync pytest plugins/_shared/tests -v` — all green.
2. `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x` — no regression in installer tests.
3. `uv run --no-sync pytest plugins/proj -x` — proj plugin tests still green (cli.py changes don't break SessionStart hook flow).
4. Manual on this host: `cpm-install --reinstall`, restart Claude Code, verify `proj_session_context` returns the active project and the YAML at `~/.claude/proj-session.yaml` is keyed by `claude-bin`'s pid (cross-check via `pgrep claude-bin`). Verify `~/.claude/proj-session-markers/` is gone after first `proj_load_session` call.

## Out of scope

- **Re-keying existing `~/.claude/proj-session.yaml` entries** written under wrong pids
  (uv pids, etc.) — they get GC'd by `_gc_dead_pids` on next `write_active`. No special
  migration needed.
- **Public API rename** — `get_claude_session_key()` keeps its name; only internals change.
  All callers (read_active, write_active, clear_active, tests) work unchanged.
- **Backward-compat shim for `CPM_CLAUDE_CODE_CMDLINE_MATCHER`** — env var becomes a no-op
  (silently ignored). Documented in changelog. Anyone with that var set sees it stop
  affecting behavior; the new resolver doesn't need it.
- **`_shared/proj_load_session` socket bypass** — orthogonal; the existing direct write
  path in `cmd_session_start` (line 252) still works because `set_session_active` keys via
  the new resolver.

## Risks

- **EXECPATH absent**: pre-EXECPATH Claude Code or non-Claude environments → `os.getpid()`
  fallback (same as today). YAML stays usable but keyed by "I'm my own session". Not a
  regression — same as today's regex-doesn't-match case.
- **Non-Linux portability**: `psutil.Process.exe()` works on macOS (returns absolute exe
  path) and Linux. Code stays portable. (Today's `/proc/<pid>/exe` realpath lookup would
  not be portable — this design uses psutil for that reason.)
- **Marker dir cleanup races**: if two cpm processes both call `write_active` at near-
  identical times after upgrade, both might call `shutil.rmtree`. `ignore_errors=True` (or
  `with suppress(OSError)`) makes this a no-op for the loser. Acceptable.
- **Subagent edge case**: a subagent (Task tool) inherits its parent Claude Code's pid via
  `os.getppid()`. The resolver returns the parent Claude pid — correct: the subagent's
  session state should live in the parent's slot. Sub-MCP-servers spawned by a subagent
  follow the same chain.
