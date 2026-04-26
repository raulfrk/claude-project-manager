# TMPDIR Audit (router_health.py + wiki_filter.py) — Design

**Date**: 2026-04-26
**Status**: approved
**Tracks todo**: 783

## Problem

Two hardcoded `"/tmp"` paths in proj plugin still don't honor `TMPDIR`. Same drift pattern as the dispatch.py + cli.py bug (commit 032da18e), in lower-impact code paths:

1. `plugins/proj/server/server/lib/router_health.py:38` — health-check cache file at `f"/tmp/claude-cpm-health-{os.getppid()}.cache"`. Single writer per session today; symptom is silent "no cached health" recheck on TMPDIR-mismatch hosts (cache file written to `/tmp` while reader looks for `/tmp` → works; if both writer and reader are in the same proj process, they agree). Risk is low, but inconsistent w/ the rest of the codebase.
2. `plugins/proj/server/server/tools/wiki_filter.py:48` — wiki-ingest filtered-session tmp file at `Path("/tmp") / f"wiki-ingest-{uuid.uuid4()}.md"`. Single-writer-single-reader in the same proj process; caller deletes after the wiki subagent returns. No cross-process coordination → TMPDIR mismatch wouldn't bite. Inconsistent only.

## Goal

Replace both hardcoded `"/tmp"` paths with `os.environ.get("TMPDIR", "/tmp")` for consistency w/ `hook_transport.dual_transport::SOCKET_DIR` (the canonical pattern in this codebase).

## Non-goals

- Use `tempfile.gettempdir()` instead. The codebase consistently uses `os.environ.get("TMPDIR", "/tmp")` — alignment beats alternative.
- Add tests. Both paths are single-writer-single-reader in-process; no cross-host TMPDIR-mismatch test catches them. Existing tests cover their callers' behavior.
- Bump proj plugin version for this fix alone — rides along on 778's bump (per user direction at Phase 0).

## Architecture

Two single-line changes:

**`plugins/proj/server/server/lib/router_health.py:38`**:

```python
# Before
return Path(f"/tmp/claude-cpm-health-{os.getppid()}.cache")  # noqa: S108

# After
tmpdir = os.environ.get("TMPDIR", "/tmp")  # noqa: S108
return Path(f"{tmpdir}/claude-cpm-health-{os.getppid()}.cache")
```

**`plugins/proj/server/server/tools/wiki_filter.py:48`**:

```python
# Before
tmp_path = Path("/tmp") / f"wiki-ingest-{uuid.uuid4()}.md"  # noqa: S108

# After
tmpdir = os.environ.get("TMPDIR", "/tmp")  # noqa: S108
tmp_path = Path(tmpdir) / f"wiki-ingest-{uuid.uuid4()}.md"
```

In each file: `os` is already imported at module top.

## Risks Accepted

- No tests added. Risk is low because both call sites are single-process; functional behavior is unchanged on default-TMPDIR hosts.
- proj plugin version not bumped here; rides along on 778's bump in the same parallel batch.
