# Proj session multi-session design (todo 724)

**Status**: approved (user confirmed Approach A via revdiff 2026-04-24)
**Date**: 2026-04-24
**Branch**: feat/724-proj-session-multi
**Todo**: 724 — Investigate proj-session.yaml — single-active-project design blocks concurrent multi-session workflows
**Decision**: Approach A — ppid-scoped single file. See §Chosen approach and §Rationale for choosing A.

## Problem

`~/.claude/proj-session.yaml` currently stores a single global scalar:

```yaml
active: <project-name>
```

Any `/proj:load` from any Claude Code session overwrites this field process-wide. Two parallel Claude Code sessions working on different projects → the second `/proj:load` clobbers the first. Both sessions now disagree with the disk:

- Within a single long-running MCP process, in-memory state wins (`state.py:58-60`), so the *acting* MCP process keeps its own view — single-session safe.
- Across MCP processes (2nd Claude Code session, and — importantly — the wiki plugin which reads the file directly from its own process), the disk is authoritative → **wrong active project** in the observer.
- Any MCP restart in the first session re-reads the clobbered disk → **wrong active project** after restart.
- Downstream effects: `wiki_scope_detect` returns the wrong scope; auto-hooks (`/proj:save`, `notes_append` → `wiki_log_append`) fire against the wrong project.

## Scope signals (from brainstorming Q&A, 2026-04-24)

- **Frequency**: daily — 2+ parallel Claude Code sessions on different repos. Fix priority: high. Accept-limitation not acceptable.
- **Keying strategy**: key by session (pid/session-id). Each session gets its own `active` value.
- **Wiki decoupling**: relaxable — cross-MCP call OK if the design is cleaner, but pure file I/O is preferred if it's reasonable.

## Verification of concern (architectural — manual test not required)

From `plugins/proj/server/server/lib/state.py`:
- Line 67: `_atomic_write(_SESSION_FILE, yaml.safe_dump({"active": name}, sort_keys=False))` — any caller overwrites the single scalar.
- Line 58-60: in-memory cache wins over disk within a process.

From `plugins/wiki/server/server/tools/scope.py`:
- Line 22: `_SESSION_YAML_PATH = Path.home() / ".claude" / "proj-session.yaml"` — wiki reads this file directly, with no cross-MCP call to proj.

Together these confirm: the cross-process observer (wiki, or any MCP restart in another session) will read whatever value was last written by any session, regardless of which session's context it's supposed to serve.

## Compatibility with the native Claude Code SessionStart hook

The native SessionStart hook calls `cli.py::cmd_session_start` → sockets into proj MCP's `ctx_session_start` → detects project from cwd → `set_session_active(name)` → writes `proj-session.yaml`.

When the hook fires, it runs *inside* a specific Claude Code session's MCP subprocess. That subprocess can identify its own Claude Code parent by walking its ppid chain. Any per-session write target is reachable at hook-fire time — the redesign works cleanly with the native hook. **The hook flow does not change; only the write target changes** from global `active:` to a session-scoped slot.

A subtle consequence: `/clear` within the same Claude Code process keeps the same pid → same active project survives, which is the correct UX (clearing a conversation shouldn't unload the project). Keying by Claude Code's `session_id` UUID would reset active-project on every `/clear` — undesirable. Ppid-keying avoids that.

## Chosen approach

### A. Ppid-scoped single file (selected)

File format v2:

```yaml
schema_version: 2
active_by_claude_pid:
  "3763634":
    active: claude-project-manager
    last_seen: 2026-04-24T14:57:00
  "3812001":
    active: wiki
    last_seen: 2026-04-24T15:01:00
```

Behavior:
- Each MCP subprocess (proj, wiki, …) walks its own ppid chain to find its Claude Code ancestor pid, via `psutil.Process(os.getpid()).parents()`, taking the first ancestor whose cmdline matches a configurable Claude Code matcher (default: executable name `claude` or cmdline containing `claude`).
- Reads/writes its own pid's slot only. `set_session_active(name)` writes to `active_by_claude_pid[<own session pid>]`.
- GC on read: prune entries whose pid no longer exists (`psutil.pid_exists`) **and** `last_seen` older than a configurable threshold (default 24 h). The `and` guards against pid-reuse edge cases.
- v1 → v2 migration: on first v2 read of a file without `schema_version`, migrate the single `active: <name>` into `active_by_claude_pid[<current session pid>] = {active: <name>, last_seen: now}`. Preserves current session's active project.

Pros:
- Single file (no directory scanning, no file clutter).
- Wiki stays pure-file-I/O (no cross-MCP call) → preserves spec §3 boundary.
- `/clear`-safe (session pid stable across `/clear`).
- Native hook compatible without protocol changes.

Cons:
- Ppid-chain walk depends on process-name matching — slightly fragile if Claude Code is renamed or wrapped. Mitigated by a configurable matcher + unit tests over mocked process trees.
- Requires `psutil` as a proj-plugin dependency (already widely used; small install cost).

## Rejected alternatives

### B. Per-pid files

`~/.claude/proj-session-<claude-pid>.yaml`, each containing the current v1 schema `{active: <name>}`.

Each MCP picks its file path via the same ppid-walk as A.

Pros:
- No concurrent-writer concerns on a single file.
- Per-file schema identical to v1 (simpler migration).

Cons:
- File clutter in `~/.claude/`.
- GC requires directory scan + pid check for each file.
- Atomic semantics are identical to A anyway (tmpfile-rename), so the "no concurrent writer" benefit is small.

### C. Drop file, use cross-MCP call

- Revert 705 semantics: proj keeps `active` in-memory only (pre-file-backed).
- Wiki's `wiki_scope_detect` calls `mcp__proj__proj_get_active` via MCP instead of reading a file.

Pros:
- No file, no concurrency, no schema migration.
- Conceptually simplest.

Cons:
- Breaks the original §3 wiki↔proj decoupling. User said OK, but this is a stronger runtime coupling than a shared file.
- Adds MCP-roundtrip latency to every wiki scope read.
- Wiki scope detection fails if proj MCP is down or slow.

## Rationale for choosing A

Best fit for:
- Daily multi-session workflow (main driver).
- Native Claude Code SessionStart hook compatibility (no protocol change).
- Preserves the wiki↔proj decoupling (spec §3) — wiki stays pure file I/O.

The only real complexity is the ppid-walk — roughly 10–20 lines of code with psutil, unit-testable via mocked process trees. Matcher configurable via env var (`CLAUDE_CODE_CMDLINE_MATCHER`) for robustness against rebrands.

## Open questions (to resolve during planning)

1. **Ppid-walk reliability**: is the `claude` cmdline match robust enough across install methods (native binary, npx, docker)? Do we need a fallback (e.g., also accept `node.*claude` pattern)?
2. **GC threshold**: 24 h default for `last_seen` — too short? Too long? Pid reuse on Linux has ~32k wraparound; `last_seen` guards this.
3. **Tests**: do we mock `psutil.Process.parents()` and `psutil.pid_exists`, or do we add a thin injectable `_get_claude_session_key()` that tests can monkey-patch?
4. **Wiki changes needed?**: if wiki's `_read_active_from_session()` just does the same walk, the change is local to a shared helper. Proposal: move the walk + file-read into a `plugins/_shared/session_key/` helper that both proj and wiki import.

## Non-goals

- Multi-project-per-session (two active projects in one Claude Code session). Not requested.
- Cross-machine sync of session state. Out of scope.
- Automatic session_id propagation via env var (would require Claude Code changes; not our repo).

## Next step

Write plan via `superpowers:writing-plans`.
