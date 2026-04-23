# Bundled cleanups: 687 + 691 + 692 + 700 — Design

**Date**: 2026-04-23
**Branch**: `feat/687-691-692-700-bundled-cleanups`
**Worktree**: `/home/raul/worktrees/cpm/feat-687-691-692-700-bundled-cleanups`
**Precedent**: `2026-04-16-tech-debt-635-648-651-design.md` (bundled small-fix spec)

## 1. Goal

Ship four unrelated small-to-medium cleanups as one bundled effort, ordered so the most foundational change (the `check_shared_version.py` validator extension) lands first and is dogfooded by the subsequent `_shared` version bump.

Closed out of scope before this branch: **689** + **690** (commit `5c01b0a`, already merged to dev, verified to match original todo descriptions).

Explicitly deferred: **688** (Karpathy wiki plugin, in-flight on `feat/688-karpathy-wiki-plugin` with its own spec and paused revdiff review).

## 2. Todos covered

| ID  | One-line              | Target files                                                                          | Size     |
| --- | --------------------- | ------------------------------------------------------------------------------------- | -------- |
| 692 | Extend version-bump validator to check all `uv.lock` files                            | `scripts/check_shared_version.py`                                   | medium   |
| 691 | Adopt robust `Path.home` patch pattern in 3 installer tests                           | `installer/tests/flow/test_installer_flow.py`                       | small    |
| 687 | Refine 685 rule for local-ahead-of-origin edge case                                   | `plugins/_shared/claudemd/managed_section.md` + test               | small    |
| 700 | New managed CLAUDE.md bullet: avoid unverified assumptions, fact-check via search     | `plugins/_shared/claudemd/managed_section.md` + test               | small    |

`_shared` version bump (0.4.10 → 0.4.11) covers the 687 + 700 content changes in a single bump.

## 3. Ordering + rationale

**A → B → C → D**:

1. **692** — ship the extended validator first. Unit-test it against a synthetic `_shared` bump. This is the only change that touches commit-time behavior, so landing it first means the rest of the branch's commits (especially the `_shared` bump in step 4) will exercise it.
2. **691** — independent test-file polish. Ordering placement is after 692 because 691 edits the same test suite that landed in `5c01b0a` for 689/690, and doing it before 692 would not exercise the new validator (no `_shared` touch).
3. **687** + **700** — land as one commit (or two adjacent commits sharing the same `_shared` version bump). The bump triggers `uv.lock` regeneration across root + 7 plugin dirs. With 692 now active, forgetting to run `just sync` at the end triggers a clean commit-blocking error instead of the silent post-merge drift observed in commit `f157632`.

Rejected alternative orderings:

- **Content-first (687+700 → 691 → 692)** — 692 gets no dogfood run on this branch.
- **Fully parallel** — two commits touching `_shared/pyproject.toml` race on the version number; requires coordination that single-threaded ordering sidesteps.

## 4. Detailed semantics

### 4.1 Todo 692 — extend `check_shared_version.py`

**Current behavior** (`scripts/check_shared_version.py`): when any `plugins/_shared/*.py` file is staged, verify that `plugins/_shared/pyproject.toml` version differs between `HEAD` and the staged index. If unchanged → fail.

**New behavior**: additionally, when the version DID bump, verify every expected `uv.lock` file pins the new `claude-hook-transport` version in its staged content. Fail listing each drifted lockfile.

**Lockfile roster** (hardcoded constant in the script):

```python
LOCKFILES = [
    "uv.lock",  # repo root (installer)
    "plugins/_shared/uv.lock",
    "plugins/router/server/uv.lock",
    "plugins/proj/server/uv.lock",
    "plugins/worktree/server/uv.lock",
    "plugins/todoist/server/uv.lock",
    "plugins/trello/server/uv.lock",
    "plugins/jira/server/uv.lock",
    "plugins/confluence/server/uv.lock",
]
```

(Note: `confluence` is deliberately included here even though the `justfile` `_PLUGIN_DIRS` constant omits it. That is tracked as a separate follow-up — see §7.)

**Version extraction from a lockfile**: parse the staged `uv.lock` content, look for the `claude-hook-transport` package block, read its `version = "..."` line. For the `_shared` lockfile, the package name is `claude-hook-transport` itself so match on `name = "claude-hook-transport"` then the next `version = "..."` line inside the same block.

**Detection trigger**: the check runs only when both of these hold in the staged index:

- `plugins/_shared/pyproject.toml` version changed vs `HEAD:`
- the new version is syntactically valid (non-empty semver-ish string)

If the version *did not* change (existing behavior path), skip the lockfile check entirely; existing ".py staged without version bump" error remains.

**Missing / unstaged lockfile**:

- Lockfile not present on disk → flag as drift (user removed it or never ran `just sync`).
- Lockfile on disk but not staged → flag as drift, hint "run `git add <path>`".
- Lockfile staged but version drift → flag with expected vs actual.

**Exit**: non-zero with a list; instruction to run `just sync && git add <drifted-paths>` and retry.

**Test coverage** (new `scripts/tests/test_check_shared_version.py` if none exists, else add to existing):

- baseline: no `_shared` .py staged → returns 0 (unchanged)
- `_shared` .py staged, no version bump → returns 1 (unchanged)
- version bump + all lockfiles staged with new version → returns 0
- version bump + one lockfile missing the new version → returns 1, output names the file
- version bump + one lockfile absent from disk → returns 1
- version bump + one lockfile on disk but not staged → returns 1
- `confluence` lockfile excluded → runs at tree top; not applicable to unit tests

**Dogfooding**: after 692 lands, step 4 (687+700 `_shared` bump commit) must successfully pass the new check, confirming `just sync` was run. If the check fails, we fix the drift before committing 687+700.

### 4.2 Todo 691 — `Path.home` patch pattern

**Current pattern** (added in `5c01b0a`):

```python
mock_ems.assert_called_once_with(Path.home() / ".claude" / "CLAUDE.md")
```

Both sides call `Path.home()` at live-test time → tautology under any future `Path.home` patch at module scope.

**Target pattern** (mirrors existing `test_reinstall_reset_configs_deletes_yamls`):

```python
def test_update_calls_ensure_managed_section(self, tmp_path: Path) -> None:
    with (
        patch("installer.flow.installer_flow.Path.home", return_value=tmp_path),
        patch("installer.flow.installer_flow.ensure_managed_section") as mock_ems,
        # ... existing patches ...
    ):
        # ... existing body ...
    mock_ems.assert_called_once_with(tmp_path / ".claude" / "CLAUDE.md")
```

**Applies to 3 tests** (all added/modified in `5c01b0a`):

1. `test_install_selects_plugins_and_executes` (line 302 — pre-existing test, new assertion added in `5c01b0a`)
2. `test_update_calls_ensure_managed_section` (newly added in `5c01b0a`)
3. `test_reinstall_calls_ensure_managed_section` (newly added in `5c01b0a`)

**Scope**: only add the `Path.home` patch where `mock_ems.assert_called_once_with(...)` exists. Other patches in the same test bodies are unchanged.

**Verification**: after the change, `uv run pytest installer/tests/flow/test_installer_flow.py -k ensure_managed_section` passes. Temporarily break `_run_install`'s call target (e.g., to `Path("/wrong") / ".claude" / "CLAUDE.md"`) and confirm each of the 3 tests fails with an argument-mismatch, not a tautological pass.

### 4.3 Todo 687 — local-ahead-of-origin guard for 685 rule

**Current bullet** (`plugins/_shared/claudemd/managed_section.md` bullet 18):

> **Sync worktree to remote after `wt_create`** — After a successful `mcp__plugin_worktree_worktree__wt_create` call, run `git fetch origin` and then `git reset --hard origin/<base-branch>` inside the returned `worktree_path` before any edits or agent dispatch. `wt_create` already resets to local HEAD and cleans untracked files, but does not fetch — the local base branch may lag `origin/<base>`. This ensures agents start from the latest remote state. Skip only when the worktree was created explicitly from a non-remote branch (e.g. a local-only experimental branch).

**Refined bullet** (same IDs; user chose "Reset to local base instead of origin when ahead"):

> **Sync worktree to remote after `wt_create`** — After a successful `mcp__plugin_worktree_worktree__wt_create` call, run `git fetch origin` inside the returned `worktree_path`, then decide:
>
> - If `git rev-list origin/<base-branch>..<base-branch>` is **empty** (local not ahead of origin): run `git reset --hard origin/<base-branch>` — picks up remote commits the local `<base>` lags behind.
> - If `git rev-list origin/<base-branch>..<base-branch>` is **non-empty** (local ahead of origin — unpushed commits exist): run `git reset --hard <base-branch>` instead — preserves unpushed work on the local `<base>` (which `wt_create` already left at its original HEAD, but the clean + checkout may have cleared uncommitted state we want to match).
>
> This runs before any edits or agent dispatch. Skip the entire check only when the worktree was created from a non-remote branch (e.g., a local-only experimental branch).

**Test update** (`plugins/_shared/tests/test_claudemd_package.py`): the existing `TestManagedSectionContent` class likely asserts the bullet contains the tokens `wt_create` and `reset --hard`. Add an assertion for the new discriminator: `rev-list origin/` (pinned so the guard wording can't silently drop).

**Re-evaluation hook**: the refined rule is longer. If real-world traces show Claude still struggles to parse it correctly, the follow-up is to move the guard into a `wt_create` post-hook, not to keep growing the prose.

### 4.4 Todo 700 — fact-checking bullet

**User's framing**: "general functioning rule, avoid making too many assumptions and instead rely on facts by searching and researching."

**Placement**: new bullet 19 (after bullet 18 "Sync worktree" rule).

**Proposed wording**:

> **Verify before asserting** — Before claiming a file, function, flag, path, API, test, commit, or configuration exists or behaves a certain way, verify it with the appropriate tool: Read for file contents, Grep for symbols or strings, Bash/git for repository state, WebFetch or WebSearch for external docs. Do not invent file paths, function signatures, config keys, commit SHAs, or tool behavior from pattern-matched priors. When memory recall names a concrete artifact, re-check that the artifact still exists before acting on it. This rule fires mid-task — not only at completion — and complements `superpowers:verification-before-completion` (which runs at the claim-work-done boundary).

**Why standalone**: piggy-backing onto the existing `superpowers` bullet would merge two distinct concerns (skill invocation vs fact-checking discipline). The `auto-capture` and `Interactive Q&A` bullets are precedent for standalone rules.

**Test update** (`plugins/_shared/tests/test_claudemd_package.py`): add an assertion pinning the distinctive phrase `"Verify before asserting"` and a representative sub-token (e.g. `"WebFetch or WebSearch"`) in `MANAGED_SECTION`.

**Grounding cases** (the kinds of drift this rule targets):

- Fabricated filenames: "I fixed it in `scripts/check_locks.py`" when no such file exists.
- Hallucinated APIs: recommending `todo_batch_complete` when the tool is actually `todo_complete(todo_ids=[...])`.
- Stale memory recall: "The spec is at X" without checking whether the file still lives there.
- Confident commit-message prose that misdescribes the diff (see the commit `f157632` case this branch itself uncovered).

### 4.5 Shared `_shared` version bump + lockfile regen

**Version**: `0.4.10 → 0.4.11`.

**Commit sequence** (on this branch):

1. feat/test for 692 — no `_shared` touch, no version bump.
2. test polish for 691 — no `_shared` touch.
3. managed-section edits for 687 + 700 — includes `_shared/pyproject.toml` version bump.
4. run `just sync` at repo root — regenerates root `uv.lock`, `plugins/_shared/uv.lock`, and 7 plugin server `uv.lock` files.
5. `git add` all drifted lockfiles + amend-free new commit that includes them.
6. attempt to commit → 692's new check runs → PASS confirms all lockfiles reference `claude-hook-transport 0.4.11`.

If step 6 fails, that's a genuine dogfood catch: some lockfile didn't regenerate. Fix the drift (likely `uv sync --directory <dir>` for the missing one) and retry.

## 5. Testing

| Todo | Test(s)                                                                                 |
| ---- | --------------------------------------------------------------------------------------- |
| 692  | New unit tests in `scripts/tests/test_check_shared_version.py` covering 6 cases (§4.1) |
| 691  | Existing `test_installer_flow.py` tests still pass; add a negative-path spot-check to prove the new assertions are not tautological. |
| 687  | `test_claudemd_package.py` assertion pinning refined-rule discriminator.                |
| 700  | `test_claudemd_package.py` assertions pinning new bullet phrase + sub-token.             |
| All  | `just test` green at repo root — runs pytest across all plugins + installer.             |

## 6. Risk + rollback

Each todo is independently revertable. The bundled commit structure is:

- Commit 1: 692 validator + tests
- Commit 2: 691 test polish
- Commit 3: 687 + 700 managed-section edits + `_shared` bump + regenerated lockfiles

Rollback: drop any commit with `git revert`. Dependencies flow forward only — Commit 3 does *not* require Commit 1 to be present (the new validator is active only when `_shared` version bumps, and reverting Commit 1 before Commit 3 is uncommon).

**CI risk** (687 + 700 bullet changes): `test_claudemd_package.py` may have an exact-content snapshot that needs regeneration. Check snapshot files before committing; regenerate if needed.

**692 validator risk**: a buggy lockfile-version extraction could produce false positives, blocking all later `_shared` bumps. Mitigation: the initial landing commit runs the new validator only in explicit test cases, not in production mode. Production mode activates on first real `_shared` bump (Commit 3 in this branch).

## 7. Follow-ups (out of scope)

- **`justfile` `_PLUGIN_DIRS` missing `confluence`** — surfaced by 692's lockfile enumeration. File a separate todo: add `plugins/confluence/server` to the justfile `_PLUGIN_DIRS` constant so `just sync` and `just test` include it. Trivially 1 line.
- **`just sync` automation on `_shared` bump** — 692 validates; doesn't automate. If devs repeatedly hit the new check, consider a genuine auto-regen pre-commit hook (rejected option from brainstorm).
- **687 rule complexity** — if the longer rule still causes parse failures, promote to a `wt_create` server-side post-hook.

## 8. Acceptance criteria

- [ ] `scripts/check_shared_version.py` handles all 6 unit-test cases per §4.1.
- [ ] All 3 installer tests named in §4.2 use `patch("installer.flow.installer_flow.Path.home", return_value=tmp_path)` and assert against `tmp_path / ".claude" / "CLAUDE.md"`.
- [ ] `plugins/_shared/claudemd/managed_section.md` bullet 18 reflects the refined 685 rule (§4.3).
- [ ] `plugins/_shared/claudemd/managed_section.md` gains bullet 19 with the §4.4 wording.
- [ ] `plugins/_shared/pyproject.toml` version is `0.4.11`.
- [ ] All 9 `uv.lock` files staged in Commit 3 reference `claude-hook-transport` version `0.4.11`.
- [ ] `just test` passes at repo root.
- [ ] Todos 687, 691, 692, 700 closed with a reference to the branch merge commit.
