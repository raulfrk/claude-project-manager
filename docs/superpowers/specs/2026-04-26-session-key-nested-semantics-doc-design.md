# session_key Nested-Session Semantics Documentation — Design

**Date**: 2026-04-26
**Status**: approved
**Tracks todo**: 777

## Problem

`get_claude_session_key()`'s docstring explains the outermost-match algorithm + iteration-order invariant but doesn't document what happens for nested Claude sessions (Task-tool subagents, `--continue` re-launches). The current behavior (subagents inherit parent's session_key by walking up to the parent's outer claude) is implicit. Future readers / debuggers may misread this as a bug.

## Goal

Add one paragraph to the docstring that explicitly states: subagents share parent's session_key by design (outermost-match returns parent's outer-claude pid). One-off behavior; no env-var override surfaces today.

## Non-goals

- Add an env-var override mechanism (not requested).
- Add an integration test mocking 3-claude chain (cost/value mismatch — paragraph documents the invariant; test would be redundant).
- Touch any code (docstring-only change).

## Architecture

Single-file change: `plugins/_shared/session_key/session_key.py`. Insert paragraph after the existing "Iteration-order invariant" paragraph in `get_claude_session_key()`'s docstring.

```
Nested-session semantics: Claude Code subagent / ``--continue`` re-launches
share a process tree with their parent. Outermost-match resolution returns
the parent session's claude pid — subagents read/write the parent's
``proj-session.yaml`` slot. This is by design: subagents inherit project
context from their invoker. A future subagent that wants its own session
state would need an explicit env-var override (e.g. CLAUDE_CODE_SESSION_PID);
not a need surfaced today.
```

## Risks Accepted

- `_shared/*.py` change triggers `Check _shared version bump` pre-commit → version bump 0.4.38 → 0.4.39 + 10-lockfile cascade. Heavy ceremony for a docstring paragraph; accepted as the cost of the pre-commit invariant.
