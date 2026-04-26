# session_key Nested-Session Semantics Documentation — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Append one paragraph to `get_claude_session_key()`'s docstring explaining nested-session inheritance behavior. Doc-only.

**Architecture:** Single insertion in `plugins/_shared/session_key/session_key.py`. Triggers `_shared` version bump + lockfile cascade.

**Tech Stack:** Markdown / Python docstring.

**Spec:** `docs/superpowers/specs/2026-04-26-session-key-nested-semantics-doc-design.md`
**Todo:** 777

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `plugins/_shared/session_key/session_key.py` | Modify | Add nested-session paragraph after "Iteration-order invariant" paragraph in `get_claude_session_key()` docstring |
| `plugins/_shared/pyproject.toml` | Modify | Bump `__version__` 0.4.38 → 0.4.39 |
| 10 lockfiles (1 root + 1 _shared + 8 plugin/server) | Modify | Refresh via `just sync` |

---

## Task 1: Insert nested-session paragraph

**Files:**
- Modify: `plugins/_shared/session_key/session_key.py` (after the "Iteration-order invariant" paragraph)

- [ ] **Step 1: Locate the insertion point**

```bash
cd /home/raul/worktrees/cpm/fix-777-session-key-nested-semantics
sed -n '54,60p' plugins/_shared/session_key/session_key.py
```

Expected output:

```
    Iteration-order invariant: ``psutil.Process().parents()`` yields ancestors
    immediate-first (ascending toward init), so the LAST recorded match is the
    outermost. The ``test_outermost_match_*`` regression tests pin this; if
    upstream ever inverts the order, those tests fail loud.

    EXECPATH-unset fallback: returns ``os.getppid()``. This handles plugin MCP
```

The new paragraph goes between the "...fail loud." line and the "EXECPATH-unset fallback:" line.

- [ ] **Step 2: Apply the edit via the Edit tool**

`old_string` (must match exactly):

```
    Iteration-order invariant: ``psutil.Process().parents()`` yields ancestors
    immediate-first (ascending toward init), so the LAST recorded match is the
    outermost. The ``test_outermost_match_*`` regression tests pin this; if
    upstream ever inverts the order, those tests fail loud.

    EXECPATH-unset fallback: returns ``os.getppid()``.
```

`new_string`:

```
    Iteration-order invariant: ``psutil.Process().parents()`` yields ancestors
    immediate-first (ascending toward init), so the LAST recorded match is the
    outermost. The ``test_outermost_match_*`` regression tests pin this; if
    upstream ever inverts the order, those tests fail loud.

    Nested-session semantics: Claude Code subagent / ``--continue`` re-launches
    share a process tree with their parent. Outermost-match resolution returns
    the parent session's claude pid — subagents read/write the parent's
    ``proj-session.yaml`` slot. This is by design: subagents inherit project
    context from their invoker. A future subagent that wants its own session
    state would need an explicit env-var override (e.g. CLAUDE_CODE_SESSION_PID);
    not a need surfaced today.

    EXECPATH-unset fallback: returns ``os.getppid()``.
```

- [ ] **Step 3: Verify the change**

```bash
cd /home/raul/worktrees/cpm/fix-777-session-key-nested-semantics
grep -A3 'Nested-session semantics' plugins/_shared/session_key/session_key.py | head -8
```

Expected: prints the new paragraph including the closing line "...not a need surfaced today.".

---

## Task 2: Bump _shared version + sync lockfiles

- [ ] **Step 1: Bump `__version__`**

Edit `plugins/_shared/pyproject.toml`:

```
- version = "0.4.38"
+ version = "0.4.39"
```

- [ ] **Step 2: Regenerate lockfiles**

```bash
cd /home/raul/worktrees/cpm/fix-777-session-key-nested-semantics
just sync
```

Expected: 10 lockfiles updated to reflect `claude-hook-transport==0.4.39`.

---

## Task 3: Pre-commit + commit

- [ ] **Step 1: Stage**

```bash
cd /home/raul/worktrees/cpm/fix-777-session-key-nested-semantics
git add plugins/_shared/session_key/session_key.py plugins/_shared/pyproject.toml
git add -u "*.lock" "uv.lock"
```

- [ ] **Step 2: Pre-commit**

```bash
cd /home/raul/worktrees/cpm/fix-777-session-key-nested-semantics
uv run pre-commit run --all-files
```

Expected: ruff, ruff-format, basedpyright, Auto-update README, `Check _shared version bump` all PASS.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs(session_key/777): document nested-session semantics in resolver docstring

Outermost-match resolution returns the parent session's claude pid for
nested Claude scenarios (subagent / --continue re-launches). Behavior
was correct but undocumented; this paragraph makes the design explicit
so future readers don't misread it as a bug.

No code change, no test change. _shared version bump 0.4.38 → 0.4.39
+ 10-lockfile cascade per pre-commit hook on _shared/*.py edits.

Spec: docs/superpowers/specs/2026-04-26-session-key-nested-semantics-doc-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Acceptance Criteria

1. ✅ `get_claude_session_key()` docstring contains the new "Nested-session semantics:" paragraph.
2. ✅ `_shared` version bumped 0.4.38 → 0.4.39.
3. ✅ 10 lockfiles updated via `just sync`.
4. ✅ Single commit on the branch w/ message starting `docs(session_key/777):`.
5. ✅ Pre-commit hooks all PASS.
