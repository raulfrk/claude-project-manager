# SessionStart Hook Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two independent root causes that both cause silent SessionStart hook failure ("no active project" after session start): (a) `uv run` cold-start exceeds 10s hook timeout, (b) session-key resolver returns INNER (transient Claude fork) instead of OUTER (long-lived session owner).

**Architecture:** Two surgical changes in two files. (1) `plugins/proj/hooks/hooks.json` — replace `uv run python` with direct `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python` for SessionStart/SessionEnd/PreCompact. (2) `plugins/_shared/session_key/session_key.py::get_claude_session_key` — change first-match to outermost-match in ancestor walk; drop `os.getppid()` fast path entirely. Single `psutil.Process().parents()` walk records every EXECPATH-matching ancestor and returns the last (outermost) match.

**Tech Stack:** Python 3.13, `psutil` (process tree walk), `pytest` (tests via `monkeypatch`), `uv` (dep mgmt — for install only, NOT for runtime hook invocation post-fix), `basedpyright` + `ruff` (pre-commit), bash (manual smoke).

**Spec:** `docs/superpowers/specs/2026-04-26-session-start-hook-reliability-design.md`
**Todos:** 774 (uv-run cold-start), 775 (resolver fork bug)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `plugins/_shared/session_key/session_key.py` | Modify (lines 30-69) | Replace `get_claude_session_key()` body — outermost-match walk, no fast path |
| `plugins/_shared/tests/test_session_key.py` | Modify | Update 2 existing tests (mock changes); add 3 new tests |
| `plugins/proj/hooks/hooks.json` | Modify (3 entries) | Replace `uv --directory ... run python` w/ direct `.venv/bin/python` |
| `plugins/_shared/_shared/__init__.py` *(if version bump required)* | Modify | Bump `__version__` per repo's "_shared version bump" pre-commit hook |

No new files. No installer changes. No CLI changes.

---

## Setup

### Worktree creation

This work touches `_shared`, which other plugins import. Use a dedicated worktree to avoid cross-contamination with any in-flight branches.

- [ ] **Step 1: Create worktree from dev**

Run via the worktree MCP tool:

```
mcp__plugin_worktree_worktree__wt_create(
    repo_label="claude-project-manager",
    branch_name="fix/session-start-hook-reliability",
    base_branch="dev"
)
```

Capture the returned `worktree_path` — every subsequent file edit, git command, and pytest invocation in this plan runs from inside that path.

- [ ] **Step 2: Sync worktree to origin/dev (per CLAUDE.md rule)**

Inside the worktree path:

```bash
git fetch origin
# Check if local dev is ahead of origin/dev:
git rev-list origin/dev..dev
```

- Output empty (local dev not ahead) → `git reset --hard origin/dev`
- Output non-empty (local dev has unpushed commits) → `git reset --hard dev`

Expected after reset: `git log -1 --format='%h %s'` shows the most recent dev commit (matches `git log origin/dev -1` if first branch).

- [ ] **Step 3: Confirm baseline tests green**

```bash
cd plugins/_shared && uv run pytest tests/test_session_key.py -v
```

Expected: all existing tests PASS (baseline).

---

## Task 1: Add Outermost-Match Regression Test (failing)

**Files:**
- Modify: `plugins/_shared/tests/test_session_key.py` (append to `TestGetClaudeSessionKey` class)

This is the bug-775 reproduction test. Drives the algorithm change.

- [ ] **Step 1: Write the failing test**

Add to `plugins/_shared/tests/test_session_key.py` inside `class TestGetClaudeSessionKey`, after `test_realpath_normalization` (around line 161):

```python
    def test_outermost_match_when_multiple_claude_ancestors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bug 775 regression: when both INNER and OUTER claude-bin processes
        appear in the ancestor chain (because Claude self-forks for hook
        execution), the resolver must return OUTER (outermost match), not
        INNER (first match).

        Process tree under SessionStart hook (CLI's view, walking up):
            shell → INNER claude-bin → OUTER claude-bin → terminal/launcher
        Both INNER and OUTER exes match EXECPATH; the launcher does not.
        Expected resolver result: OUTER.pid.
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 5000)  # immediate parent: shell

        shell_proc = _FakeProc(pid=5000, exe="/bin/bash")
        inner_claude = _FakeProc(pid=100, exe="/usr/bin/claude")
        outer_claude = _FakeProc(pid=200, exe="/usr/bin/claude")
        launcher = _FakeProc(pid=1, exe="/sbin/init")

        # parents() yields ancestors immediate-first (psutil contract).
        def fake_process(pid=None):
            if pid == 5000:
                return shell_proc
            return _FakeProc(
                pid=os.getpid(),
                parents_=[shell_proc, inner_claude, outer_claude, launcher],
            )

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        # Outermost match wins → OUTER.pid (200), NOT INNER.pid (100).
        assert sk.get_claude_session_key() == "200"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd plugins/_shared && uv run pytest tests/test_session_key.py::TestGetClaudeSessionKey::test_outermost_match_when_multiple_claude_ancestors -v
```

Expected: FAIL with `AssertionError: assert '100' == '200'` — current resolver returns first match (INNER), proving the bug.

- [ ] **Step 3: Commit the failing test (TDD red)**

```bash
git add plugins/_shared/tests/test_session_key.py
git commit -m "test(session_key/775): failing test — outermost-match for fork chain"
```

---

## Task 2: Implement Outermost-Match Resolver

**Files:**
- Modify: `plugins/_shared/session_key/session_key.py:30-69` (replace `get_claude_session_key` body)

- [ ] **Step 1: Replace the function body**

Replace lines 30-69 (the entire `get_claude_session_key` function) in `plugins/_shared/session_key/session_key.py` with:

```python
def get_claude_session_key() -> str:
    """Return the calling process's outermost Claude Code ancestor pid as a string.

    Walks ``psutil.Process().parents()`` and returns the OUTERMOST ancestor
    whose canonical exe path matches CLAUDE_CODE_EXECPATH (the env var Claude
    Code injects into every subprocess).

    Outermost-match — not first-match — because Claude self-forks for hook
    execution. The process tree under a SessionStart hook is::

        claude-bin (OUTER, long-lived, parents MCP servers)
         └─ claude-bin (INNER, transient fork for hook execution)
             └─ <shell or interpreter chain>
                 └─ python (cli.py)

    Both INNER and OUTER match EXECPATH. Only OUTER is authoritative for
    session state — it parents the MCP servers that read what hooks write.
    Returning INNER's pid (first-match) causes hooks and MCP servers to
    disagree on the session key, breaking ``proj-session.yaml`` lookups.

    No fast path: a single walk handles both MCP servers (one matching
    ancestor) and hooks (multiple matching ancestors). ``parents()`` is
    microseconds-fast.

    Falls back to ``os.getpid()`` when EXECPATH is unset (tests, non-Claude
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

- [ ] **Step 2: Run the regression test to verify it passes**

```bash
cd plugins/_shared && uv run pytest tests/test_session_key.py::TestGetClaudeSessionKey::test_outermost_match_when_multiple_claude_ancestors -v
```

Expected: PASS.

- [ ] **Step 3: Run the full session_key resolver test class**

```bash
cd plugins/_shared && uv run pytest tests/test_session_key.py::TestGetClaudeSessionKey -v
```

Expected: NEW test passes; some EXISTING tests will FAIL because their mocks relied on the old fast path returning ppid without consulting `parents()`. Specifically:

- `test_direct_parent_match_returns_ppid` — fails: `fake_parent` has empty `parents()`; new walk finds no match; falls back to `os.getpid()` instead of "1234".
- `test_realpath_normalization` — fails: same reason (`parent` has empty `parents_`).

These two tests need updated mocks. That's Task 3.

Other tests (`test_falls_back_to_own_pid_when_execpath_unset`, `test_mid_chain_ancestor_match`, `test_no_ancestor_matches_falls_back_to_own_pid`, `test_no_such_process_mid_walk_continues`) already populate `parents_` and should stay green.

- [ ] **Step 4: Do NOT commit yet** — Task 3 fixes the existing tests; commit them together with the impl.

---

## Task 3: Update Existing Tests Broken by Algorithm Change

**Files:**
- Modify: `plugins/_shared/tests/test_session_key.py` (`test_direct_parent_match_returns_ppid` ~line 63, `test_realpath_normalization` ~line 143)

The two tests that relied on the dropped fast path need updated mocks so `parents()` exposes the matching ancestor.

- [ ] **Step 1: Update `test_direct_parent_match_returns_ppid`**

Replace the existing function body (lines ~63-76) with:

```python
    def test_direct_parent_match_returns_ppid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the only matching ancestor IS the immediate parent, resolver
        returns ppid. (No fast path post-775; this exercises the walk path
        with a single matching ancestor.)
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 1234)

        claude_parent = _FakeProc(pid=1234, exe="/usr/bin/claude")

        # Process() (no arg) returns self whose parents() yields [claude_parent].
        def fake_process(pid=None):
            if pid == 1234:
                return claude_parent
            return _FakeProc(pid=os.getpid(), parents_=[claude_parent])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == "1234"
```

- [ ] **Step 2: Update `test_realpath_normalization`**

Replace the existing function body (lines ~143-161) with:

```python
    def test_realpath_normalization(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EXECPATH and ancestor exe both go through realpath() — symlinks resolve."""
        from session_key import session_key as sk

        # EXECPATH is /usr/bin/claude (a symlink); realpath → /opt/claude/bin/claude.
        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 4242)

        claude_parent = _FakeProc(pid=4242, exe="/usr/bin/claude")  # also a symlink

        def fake_process(pid=None):
            if pid == 4242:
                return claude_parent
            return _FakeProc(pid=os.getpid(), parents_=[claude_parent])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)

        def fake_realpath(p: str) -> str:
            if p == "/usr/bin/claude":
                return "/opt/claude/bin/claude"
            return p

        monkeypatch.setattr(sk.os.path, "realpath", fake_realpath)

        assert sk.get_claude_session_key() == "4242"
```

- [ ] **Step 3: Run the full resolver test class**

```bash
cd plugins/_shared && uv run pytest tests/test_session_key.py::TestGetClaudeSessionKey -v
```

Expected: all 6 tests PASS (5 original + 1 new from Task 1).

---

## Task 4: Add Test — ppid Match Does Not Short-Circuit Walk

**Files:**
- Modify: `plugins/_shared/tests/test_session_key.py` (append to `TestGetClaudeSessionKey`)

Confirms the fast path is genuinely gone: even when `os.getppid()`'s exe matches EXECPATH, resolver still walks the chain and prefers a deeper match.

- [ ] **Step 1: Add the test**

Append inside `class TestGetClaudeSessionKey`, after `test_outermost_match_when_multiple_claude_ancestors`:

```python
    def test_ppid_match_does_not_short_circuit_walk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Confirms fast path is gone (post-775).

        os.getppid() returns a pid whose exe matches EXECPATH AND there's a
        deeper ancestor that ALSO matches. The deeper (outermost) ancestor
        must win — proving resolver no longer short-circuits on ppid match.
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 100)  # immediate parent matches

        inner_claude = _FakeProc(pid=100, exe="/usr/bin/claude")
        outer_claude = _FakeProc(pid=200, exe="/usr/bin/claude")
        launcher = _FakeProc(pid=1, exe="/sbin/init")

        def fake_process(pid=None):
            if pid == 100:
                return inner_claude
            return _FakeProc(
                pid=os.getpid(),
                parents_=[inner_claude, outer_claude, launcher],
            )

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        # Even with ppid matching, outermost wins.
        assert sk.get_claude_session_key() == "200"
```

- [ ] **Step 2: Run the new test**

```bash
cd plugins/_shared && uv run pytest tests/test_session_key.py::TestGetClaudeSessionKey::test_ppid_match_does_not_short_circuit_walk -v
```

Expected: PASS.

---

## Task 5: Add Test — Dead Pid in Fork Chain

**Files:**
- Modify: `plugins/_shared/tests/test_session_key.py` (append to `TestGetClaudeSessionKey`)

Combines fork-chain w/ a dead/inaccessible mid-walk ancestor. Verifies `continue`-on-error still finds the outermost live match.

- [ ] **Step 1: Add the test**

Append inside `class TestGetClaudeSessionKey`, after `test_ppid_match_does_not_short_circuit_walk`:

```python
    def test_outermost_match_with_dead_pid_in_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One ancestor in the fork chain is dead (raises NoSuchProcess on
        .exe()). Walk must continue and return the outermost LIVE match.
        """
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 7000)

        shell_proc = _FakeProc(pid=7000, exe="/bin/bash")
        inner_claude = _FakeProc(pid=100, exe="/usr/bin/claude")
        dead_proc = _FakeProc(pid=150, exe_raises=True)
        outer_claude = _FakeProc(pid=200, exe="/usr/bin/claude")
        launcher = _FakeProc(pid=1, exe="/sbin/init")

        def fake_process(pid=None):
            if pid == 7000:
                return shell_proc
            return _FakeProc(
                pid=os.getpid(),
                parents_=[shell_proc, inner_claude, dead_proc, outer_claude, launcher],
            )

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        # Dead ancestor between INNER and OUTER does NOT short-circuit walk.
        assert sk.get_claude_session_key() == "200"
```

- [ ] **Step 2: Run the new test**

```bash
cd plugins/_shared && uv run pytest tests/test_session_key.py::TestGetClaudeSessionKey::test_outermost_match_with_dead_pid_in_chain -v
```

Expected: PASS.

---

## Task 6: Run Full Test Suite + Pre-Commit Checks

**Files:**
- None (validation only)

- [ ] **Step 1: Run full `_shared` test suite**

```bash
cd plugins/_shared && uv run pytest tests/ -v
```

Expected: all tests PASS, including the 3 new tests added in Tasks 1, 4, 5 and the 2 updated tests from Task 3.

- [ ] **Step 2: Run pre-commit on staged + changed files**

From repo root:

```bash
git add plugins/_shared/session_key/session_key.py plugins/_shared/tests/test_session_key.py
uv run pre-commit run --files \
    plugins/_shared/session_key/session_key.py \
    plugins/_shared/tests/test_session_key.py
```

Expected: all hooks pass (ruff format, ruff legacy, basedpyright, "Auto-update README" skipped, "Check _shared version bump" — see Step 3 if it fails).

- [ ] **Step 3: If "Check _shared version bump" fails, bump `_shared` version**

The pre-commit hook enforces a `__version__` bump on any `_shared/` `.py` change. Read the failure message; it will name the file holding the version. Typically `plugins/_shared/_shared/__init__.py` or the first nested `__init__.py`. Bump the patch component (e.g., `1.5.3` → `1.5.4`):

```bash
# Inspect:
grep -rn '__version__' plugins/_shared/_shared/ plugins/_shared/session_key/ | head -5
# Edit the file the grep result names — increment patch by 1.
# Re-stage + re-run pre-commit:
git add <bumped-file>
uv run pre-commit run --files \
    plugins/_shared/session_key/session_key.py \
    plugins/_shared/tests/test_session_key.py \
    <bumped-file>
```

Expected: all hooks PASS.

- [ ] **Step 4: If basedpyright reports type errors in the new code**

The new `get_claude_session_key` uses `last_match: int | None = None`. If basedpyright complains, ensure the import block at top of `session_key.py` already has `from __future__ import annotations` (it does — line 9). No additional imports needed.

If a different error appears, fix inline; do NOT silence with `# type: ignore` unless documented in `feedback_*.md` memory.

---

## Task 7: Commit Resolver Fix

**Files:**
- None (commit only)

- [ ] **Step 1: Confirm staged contents**

```bash
git status
git diff --cached --stat
```

Expected staged files:
- `plugins/_shared/session_key/session_key.py`
- `plugins/_shared/tests/test_session_key.py`
- `plugins/_shared/_shared/__init__.py` (or wherever `_shared` `__version__` lives, IF Task 6 Step 3 ran)

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(session_key/775): outermost-match resolver + drop fast path

Bug 775: get_claude_session_key() returned the FIRST EXECPATH-matching
ancestor, which under SessionStart hooks is INNER (Claude's transient
fork for hook execution), not OUTER (the long-lived session owner that
parents MCP servers). Hooks wrote proj-session.yaml keyed by INNER;
MCP servers read it keyed by OUTER; the two never agreed.

Fix: walk parents() and return the OUTERMOST EXECPATH match. Drop the
os.getppid() fast path entirely — single resolution path for hooks
and MCP servers; microseconds-scale overhead.

Tests: 3 new (fork-chain regression, ppid no-short-circuit, dead-pid
mid-chain). 2 existing (test_direct_parent_match_returns_ppid,
test_realpath_normalization) updated to populate parents() chain
instead of relying on the dropped fast path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hooks pass.

---

## Task 8: Update hooks.json — All 3 Hook Entries

**Files:**
- Modify: `plugins/proj/hooks/hooks.json` (lines 10, 23, 36)

- [ ] **Step 1: Replace SessionStart command**

Edit `plugins/proj/hooks/hooks.json`. Replace line 10:

Before:
```json
            "command": "uv --directory ${CLAUDE_PLUGIN_ROOT}/server run python -m server.cli session-start --cwd \"$CLAUDE_PROJECT_DIR\"",
```

After:
```json
            "command": "${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python -m server.cli session-start --cwd \"$CLAUDE_PROJECT_DIR\"",
```

- [ ] **Step 2: Replace SessionEnd command**

Replace line 23:

Before:
```json
            "command": "uv --directory ${CLAUDE_PLUGIN_ROOT}/server run python -m server.cli session-end --cwd \"$CLAUDE_PROJECT_DIR\"",
```

After:
```json
            "command": "${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python -m server.cli session-end --cwd \"$CLAUDE_PROJECT_DIR\"",
```

- [ ] **Step 3: Replace PreCompact command**

Replace line 36:

Before:
```json
            "command": "uv --directory ${CLAUDE_PLUGIN_ROOT}/server run python -m server.cli session-start --cwd \"$CLAUDE_PROJECT_DIR\" --compact",
```

After:
```json
            "command": "${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python -m server.cli session-start --cwd \"$CLAUDE_PROJECT_DIR\" --compact",
```

- [ ] **Step 4: Verify JSON is still valid**

```bash
python -c "import json; json.load(open('plugins/proj/hooks/hooks.json'))" && echo "JSON OK"
```

Expected: prints `JSON OK` with no traceback.

- [ ] **Step 5: Eyeball the diff**

```bash
git diff plugins/proj/hooks/hooks.json
```

Expected: 3 `command` lines changed, all `uv --directory ${CLAUDE_PLUGIN_ROOT}/server run python` → `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python`. `timeout`, `statusMessage`, `async`, `matcher` unchanged.

- [ ] **Step 6: Run pre-commit on the file**

```bash
git add plugins/proj/hooks/hooks.json
uv run pre-commit run --files plugins/proj/hooks/hooks.json
```

Expected: hooks pass (probably most are skipped — JSON files don't trigger ruff/basedpyright; `Auto-update README` may run but should be a no-op).

---

## Task 9: Commit Hook Config Fix

**Files:**
- None (commit only)

- [ ] **Step 1: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(proj/hooks/774): direct .venv/bin/python — bypass uv run cold-start

Bug 774: hooks.json invokes the CLI via 'uv --directory ... run python'
with timeout=10. On cold uv cache (post-upgrade, post-reinstall, post-
idle), 'uv run' lockfile resolution + venv hydration exceeds 60s, well
past the 10s timeout. Claude Code kills the hook silently → no project
context loaded, no error surfaced.

Fix: invoke ${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python directly. The
venv is fully hydrated by the installer's 'uv sync'; runtime hook
invocation skips uv's per-call lockfile check. Cold-start drops from
60+s to ~3.8s (verified locally).

Applied to all 3 hooks: SessionStart, SessionEnd, PreCompact. No
fallback path — if .venv is missing, hook fails loud (remediation:
'cpm-install --reinstall').

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hooks pass.

---

## Task 10: Push + Manual Smoke + Close Todos

**Files:**
- None (delivery only)

- [ ] **Step 1: Confirm local branch state**

```bash
git log --oneline origin/dev..HEAD
```

Expected: 2 commits — the resolver fix (Task 7) and the hook config fix (Task 9).

- [ ] **Step 2: Push the branch**

```bash
git push -u origin fix/session-start-hook-reliability
```

Expected: push succeeds. (If pre-push hook runs `_shared` version-bump check and complains, that's Task 6 Step 3 territory — bump locally, amend, force-push.)

- [ ] **Step 3: Decide merge path**

Two options, per `feedback_624_merge_convention.md`:

- **A. FF-merge into dev** (preferred for trunk-style work):
  ```bash
  git checkout dev && git pull origin dev
  git merge --ff-only fix/session-start-hook-reliability
  git push origin dev
  ```
- **B. Open a PR** if user wants review.

Default to A unless user requests B.

- [ ] **Step 4: Manual smoke (post-merge, on user's host)**

After dev push lands and the user reinstalls the plugin (`cpm-install --reinstall` or equivalent):

```bash
# 1. Mimic post-install state — rehydrate venv from scratch:
cd ~/.claude/plugins/cache/claude-project-manager/proj/<latest>/server
rm -rf .venv && uv sync

# 2. Optional — verify cold-cache baseline (skip if not curious):
uv cache clean

# 3. Start a fresh Claude Code session in a tracked project:
cd ~/projects/claude-project-manager
claude  # or via your usual launcher

# 4. Once Claude is up, verify:
#    - Session log shows no '[hook timed out]' entries.
#    - First message: ask Claude to call proj_session_context.
#    - Expected: returns 'claude-project-manager' (not "no active project").
```

Then verify pid agreement:

```bash
# In another terminal, while Claude is running:
pgrep -af claude-bin
# Note the OUTERMOST claude-bin pid (the long-lived one).

cat ~/.claude/proj-session.yaml
# active_by_claude_pid key MUST equal that OUTERMOST pid.
```

Expected: key in `proj-session.yaml` matches the outermost `claude-bin` pid.

- [ ] **Step 5: Multi-session safety check**

In a second terminal:

```bash
cd ~/projects/<another-tracked-project>
claude
```

Verify:
- Each session has a distinct key in `proj-session.yaml`.
- Each session sees its own active project (not the other's) via `proj_session_context`.

- [ ] **Step 6: Close todos 774 and 775**

After smoke passes, mark both todos complete via the proj plugin:

```
mcp__plugin_proj_proj__todo_complete(todo_id="774")
mcp__plugin_proj_proj__todo_complete(todo_id="775")
```

Or, if completing both at once (per CLAUDE.md `todo_batch_complete` rule):

```
mcp__plugin_proj_proj__todo_batch_complete(todo_ids=["774", "775"])
```

Expected: both todos marked done; tracking-flush + Todoist hooks fire successfully.

- [ ] **Step 7: Worktree cleanup**

```
mcp__plugin_worktree_worktree__wt_remove(worktree_path="<path-from-Setup-Step-1>")
```

Expected: worktree removed cleanly (branch already merged + pushed).

---

## Acceptance Criteria

After this plan completes:

1. ✅ `pytest plugins/_shared/tests/test_session_key.py` — all tests pass, including 3 new tests covering fork-chain (775), ppid-no-short-circuit (fast path drop), and dead-pid mid-walk.
2. ✅ `plugins/_shared/session_key/session_key.py::get_claude_session_key` walks ancestors and returns outermost EXECPATH match; no fast path.
3. ✅ `plugins/proj/hooks/hooks.json` — all 3 hooks invoke `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python` directly.
4. ✅ Manual smoke: fresh Claude session in a tracked project sees `proj_session_context` return the project on first call.
5. ✅ `proj-session.yaml` key equals outermost `claude-bin` pid (verified via `pgrep -af claude-bin`).
6. ✅ Two concurrent sessions have distinct keys; neither clobbers the other.
7. ✅ Todos 774 + 775 marked complete.
8. ✅ Pre-commit (ruff, basedpyright, _shared version bump) green.

---

## Self-Review Notes

**Spec coverage**:
- Component 1 (Hook Invocation) → Task 8.
- Component 2 (Resolver Semantics) → Tasks 1–7.
- Testing → Tasks 1, 3, 4, 5, 6 (unit) + Task 10 (manual smoke).
- Non-goals → not implemented (correct).
- Risks (`.venv` missing, fast-path microcost) → accepted; no mitigation tasks (correct per spec).

**Type consistency**: `last_match: int | None` matches `psutil` `Process.pid: int`. Fallback `str(os.getpid())` matches `int → str` conversion used elsewhere.

**Placeholders**: none — every code block is complete; every command has expected output; every file path is exact.
