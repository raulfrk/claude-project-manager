# TMPDIR Audit (router_health.py + wiki_filter.py) — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace 2 hardcoded `"/tmp"` paths with `os.environ.get("TMPDIR", "/tmp")` in proj plugin's `router_health.py` + `wiki_filter.py`. No tests, no version bump (rides along on 778's bump).

**Architecture:** 2 single-line edits in 2 files.

**Spec:** `docs/superpowers/specs/2026-04-26-tmpdir-audit-router-health-wiki-filter-design.md`
**Todo:** 783

---

## File Structure

| File | Action |
|---|---|
| `plugins/proj/server/server/lib/router_health.py:38` | Modify (single-line replacement) |
| `plugins/proj/server/server/tools/wiki_filter.py:48` | Modify (single-line replacement) |

---

## Task 1: router_health.py path swap

**Files:**
- Modify: `plugins/proj/server/server/lib/router_health.py:38`

- [ ] **Step 1: Confirm current line**

```bash
cd /home/raul/worktrees/cpm/fix-783-tmpdir-audit
sed -n '36,40p' plugins/proj/server/server/lib/router_health.py
```

Expected: line 38 contains `return Path(f"/tmp/claude-cpm-health-{os.getppid()}.cache")  # noqa: S108`. If different, STOP and ask.

- [ ] **Step 2: Apply the Edit**

Use the Edit tool with these strings:

`old_string`:

```
    return Path(f"/tmp/claude-cpm-health-{os.getppid()}.cache")  # noqa: S108
```

`new_string`:

```
    tmpdir = os.environ.get("TMPDIR", "/tmp")  # noqa: S108
    return Path(f"{tmpdir}/claude-cpm-health-{os.getppid()}.cache")
```

- [ ] **Step 3: Verify**

```bash
cd /home/raul/worktrees/cpm/fix-783-tmpdir-audit
grep -A1 'TMPDIR' plugins/proj/server/server/lib/router_health.py | head -4
```

Expected: shows the new lines.

---

## Task 2: wiki_filter.py path swap

**Files:**
- Modify: `plugins/proj/server/server/tools/wiki_filter.py:48`

- [ ] **Step 1: Confirm current line**

```bash
cd /home/raul/worktrees/cpm/fix-783-tmpdir-audit
sed -n '46,50p' plugins/proj/server/server/tools/wiki_filter.py
```

Expected: line 48 contains `tmp_path = Path("/tmp") / f"wiki-ingest-{uuid.uuid4()}.md"  # noqa: S108`. If different, STOP and ask.

- [ ] **Step 2: Apply the Edit**

`old_string`:

```
    tmp_path = Path("/tmp") / f"wiki-ingest-{uuid.uuid4()}.md"  # noqa: S108
```

`new_string`:

```
    tmpdir = os.environ.get("TMPDIR", "/tmp")  # noqa: S108
    tmp_path = Path(tmpdir) / f"wiki-ingest-{uuid.uuid4()}.md"
```

- [ ] **Step 3: Verify**

```bash
cd /home/raul/worktrees/cpm/fix-783-tmpdir-audit
grep -B1 -A1 'wiki-ingest-' plugins/proj/server/server/tools/wiki_filter.py | head -6
```

Expected: shows the TMPDIR-aware lines.

---

## Task 3: Pre-commit + commit

- [ ] **Step 1: Stage + pre-commit**

```bash
cd /home/raul/worktrees/cpm/fix-783-tmpdir-audit
git add plugins/proj/server/server/lib/router_health.py plugins/proj/server/server/tools/wiki_filter.py
uv run pre-commit run --files plugins/proj/server/server/lib/router_health.py plugins/proj/server/server/tools/wiki_filter.py
```

Expected: ruff, ruff-format, basedpyright PASS. `Check _shared version bump` PASSES (no `_shared/` changes).

If ruff-format reformats files, re-stage and re-run.

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(proj/783): TMPDIR-aware paths in router_health.py + wiki_filter.py

Two remaining hardcoded `/tmp` paths in proj plugin. Same drift pattern
as the dispatch.py + cli.py bug (commit 032da18e), in lower-impact
single-writer-single-reader code paths:

- plugins/proj/server/server/lib/router_health.py:38 — health-check
  cache file at `/tmp/claude-cpm-health-{os.getppid()}.cache`. Single
  writer per session.
- plugins/proj/server/server/tools/wiki_filter.py:48 — wiki-ingest
  filtered-session tmp file at `/tmp/wiki-ingest-{uuid}.md`. Caller
  deletes after wiki subagent returns.

Both replaced w/ `os.environ.get("TMPDIR", "/tmp")` for consistency
with the rest of the codebase (hook_transport.dual_transport::SOCKET_DIR).

No tests added — single-process call sites; default-TMPDIR hosts
unaffected. proj plugin version not bumped here; rides along on 778's
bump in the same parallel batch.

Spec: docs/superpowers/specs/2026-04-26-tmpdir-audit-router-health-wiki-filter-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

## Acceptance Criteria

1. ✅ `router_health.py:38` uses `os.environ.get("TMPDIR", "/tmp")`.
2. ✅ `wiki_filter.py:48` uses `os.environ.get("TMPDIR", "/tmp")`.
3. ✅ Single commit on the branch w/ message starting `fix(proj/783):`.
4. ✅ Pre-commit hooks PASS. No `_shared` version bump (no `_shared/` files touched).
