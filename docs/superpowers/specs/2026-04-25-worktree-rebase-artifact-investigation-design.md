# Worktree Rebase Artifact — Investigation Design Spec

**Date**: 2026-04-25
**Todo**: 735 — `Investigate worktree-rebase-artifact root cause: unstaged copies of OTHER worktrees' files appear as "modified" post-batch`
**Author**: brainstorming session (Raul + Claude Opus 4.7)
**Status**: design approved; awaiting user spec review → writing-plans

---

## Problem statement

After running parallel impl batches in separate worktrees + sequentially rebasing each branch onto evolving `dev` (post each FF-merge), at least one worktree ends up with `git status` showing unstaged "modified" entries that are actually **files belonging to a SIBLING worktree's branch**.

Reproduced 2/2 times in 2026-04-25 batches:
- D+E batch: todo 728's worktree had unstaged copies of todo 723's `installer/flow/integration_config.py` + `test_configure_wiki.py` content — files 728 never touched.
- Batch A: 729's worktree had similar unstaged junk after the merge phase; `wt_remove` failed with "modified or untracked files"; needed `force=true`.

Workaround (`git restore .` before rebase) is reliable. Root cause unknown.

## Goal

Reliable reproduction + identified root cause + targeted fix. NOT just a better workaround.

In parallel: standardize the existing workaround in the `parallel-impl-orchestration` recipe + `proj:parallel-batch-execute` skill regardless of investigation outcome.

## Non-goals

- Fix other worktree pitfalls ([[parallel-git-races]], [[wt-merge-conflict-removes-worktree]], [[stale-worktree-vs-advancing-dev]]) — separate todos.
- Generalize fix to non-cpm projects.
- Upstream git bug report (only if Phase 1 reproduces; out of scope for v1 otherwise).
- Replace the `parallel-impl-orchestration` recipe wholesale.

## Hypotheses (locked priority)

Per locked decision in brainstorm, the spec prioritizes 2 hypotheses:

1. **Pre-commit hooks writing across worktrees** — `ruff --fix`, `ruff-format`, `update-readme` are all write-back hooks. If any script (notably `scripts/update_readme.py`) resolves repo paths via `Path(__file__).parent.parent` walks or env vars rather than `git rev-parse --show-toplevel` from cwd, it could write to the wrong worktree.
2. **Test artifacts (uv, pytest, snapshot tests) writing outside worktree** — the session has untracked `installer/tests/e2e/test_snapshots_*.py` files in the main repo root, hinting that snapshot-update mode wrote there. If pytest/snapshot fixtures use absolute paths that miss the worktree boundary, this leaks. Also: shared `UV_CACHE_DIR` if not set per-worktree.

Deprioritized (will only test if 1+2 fail to reproduce):
3. Git internals (shared `.git/objects`, refs, packed-refs race) — hard to diagnose; deprioritized.
4. Stat-cache invalidation (false-positive `modified` after dev advances) — different symptom shape (would surface own files, not sibling files); ruled out unless Phase 1 finds it.

## Architecture — bisect-style investigation

Investigation philosophy: bisect from minimal-conditions outward. Each phase adds one variable; the phase where the artifact appears IS the layer responsible.

| Phase | Action | Layer eliminated/identified if reproduces |
|---|---|---|
| 0. Setup | Build deterministic repro fixture script | — |
| 1. Bare git | Repro w/ `git commit --no-verify` + no tests | git internals |
| 2. + pre-commit | Repro w/ real pre-commit hooks (cpm config) | pre-commit hooks |
| 3. + tests | Repro w/ pytest per worktree | test artifacts |
| 4. Instrument | Trace file writes from culprit layer | pinpoint exact file-write code path |
| 5. Targeted fix | Patch + regression test | resolved |
| Parallel track | Workaround codification | independent — ships anyway |

**Time-box**: Phases 1-3 ≤ 2 hours total (each phase is a 20-30 min experiment). If Phase 1 reproduces (git internals), escalate to user before continuing — that's a deeper rabbit hole.

**Storage of investigation artifacts**:
- Repro script: `scripts/repro/735-worktree-rebase-artifact.sh` (cpm-internal scripts dir; committed).
- Run logs / strace output: `tmp/735-investigation/` (gitignored, NOT committed).
- Findings: appended to wiki `[[worktree-rebase-artifact]]` page + decision log entry per managed rule 20.

## Phase 0 — Repro fixture script

Build a deterministic Bash script (`scripts/repro/735-worktree-rebase-artifact.sh`) that:

1. Creates a fresh tmpdir scratch repo (NOT inside cpm — fully isolated from project state).
2. Initializes a tiny project with `a.txt`, `b.txt`, `c.txt` containing one line each.
3. Commits to a `dev` branch.
4. Creates 3 worktrees (`feat-A`, `feat-B`, `feat-C`), each touching ONE distinct file (A→a.txt, B→b.txt, C→c.txt) with a single-line append.
5. Sequentially: in each worktree, `git commit` + `git rebase dev` + `git checkout dev` (in main) + `git merge --ff-only feat-X`.
6. Between each step, capture `git status --porcelain` + `ls -la` of every worktree's tree.
7. Emit a per-step state log to stdout.
8. Final assertion: detect any worktree where `git status` shows unstaged content NOT belonging to that worktree's branch HEAD. Pass/fail boolean.

**Idempotent**: nukes its tmpdir on each run via `rm -rf` then recreates.

**Outputs**: `pass` / `fail <details>` to stdout. Exit code 0 on pass, 1 on fail.

## Phase 1 — Bare git (no pre-commit, no tests)

Run Phase 0 script with:
- `git -c init.defaultBranch=dev init` for the scratch repo.
- `git commit --no-verify` (skip pre-commit explicitly via `git commit -n` or env).
- No test invocations.
- Trivial single-line file changes per worktree (already in fixture).

**Expected outcomes**:

- **Reproduces** → git internals OR the rebase+FF-merge sequence is responsible (possibly upstream git bug). Pause + escalate to user via `AskUserQuestion`: continue investigation OR file upstream bug OR fall back to workaround codification only.
- **Does NOT reproduce** → git alone is innocent. Proceed to Phase 2.

**Edge case to verify**: between each rebase, check git stat-cache behavior. If we see false-positive `modified` flagging worktree A's OWN files (not sibling files), that's stat-cache (different bug; document in NOTES.md but not 735).

**Exit criterion**: pass = no artifact across 3 sequential rebases.

## Phase 2 — Add pre-commit (cpm hooks active)

Phase 0 fixture too sterile (just text files, no Python). Phase 2 needs richer fixture: clone the cpm repo OR use an actual cpm worktree-base.

**Approach**: clone the cpm repo to a fresh tmpdir (so we don't pollute the live cpm worktree). In the clone, replicate the Phase 0 fixture pattern: 3 worktrees off `dev`, each touching a distinct real Python file (e.g. worktree-A → `plugins/proj/server/server/cli.py`; worktree-B → `plugins/wiki/server/server/main.py`; worktree-C → `plugins/router/server/server/main.py` — pick disjoint files). Real `pre-commit run` per commit. If `update-readme` hook doesn't trigger naturally on these files, force a touch to `marketplace.json` in one worktree to exercise the hook at least once.

**Per-hook bisection**: enable cpm's hooks one at a time. Stop at first repro:
1. ruff (--fix)
2. ruff-format
3. basedpyright
4. update-readme
5. check-shared-version

**Up-front audit** (cheap, do before bisection): read `scripts/update_readme.py` for path-resolution logic. If it uses `Path(__file__).parent.parent` walks instead of `git rev-parse --show-toplevel`, that's a strong signal it's the culprit.

**Phase 2 exit**:
- Reproduces with hook X → X is responsible. Skip to Phase 4 (instrument X).
- Reproduces only with multiple hooks combined → interaction bug. Diagnose pairwise.
- Doesn't reproduce → pre-commit innocent. Proceed to Phase 3.

## Phase 3 — Add tests (pytest per worktree)

If Phase 2 didn't repro, run pytest in each worktree's plugin dir between commit + rebase steps:

```
for each worktree:
  git commit (with full pre-commit)
  cd plugins/<plugin>/server
  uv run pytest --no-cov  (or relevant plugin's suite)
  git rebase dev
  git merge --ff-only (in main)
  check sibling worktrees for artifact
```

**Likely test culprits** (from todo 735 notes hypotheses 4 + 5):
- Snapshot tests writing to absolute paths. The session's untracked `installer/tests/e2e/test_snapshots_*.py` files in main repo root strongly suggest snapshot-update mode wrote there.
- pytest fixtures resolving paths via `Path.cwd()` or env vars pointing at a different worktree.
- `uv` cache / venv state leak if `UV_CACHE_DIR` not set per-worktree.

**Up-front audit**: read `installer/tests/e2e/test_snapshots_main.py` (and siblings) for path-resolution patterns. Look for absolute paths, `Path("/home/...")`, or `os.environ["HOME"]`-derived paths.

**Phase 3 exit**:
- Reproduces during test runs → test fixture/snapshot is responsible. Bisect by test file.
- Doesn't reproduce → exhausted hypotheses 1+2; can't repro consistently → escalate to user (time-box hit) → fall back to Phase 6 (workaround codification only) + document evidence in NOTES.md.

## Phase 4 — Instrument the culprit

Once Phase 2 OR Phase 3 identifies the layer.

**For pre-commit hook X**:
- Wrap entry script in tracer: `strace -f -e trace=openat,write -o trace.log <hook>` (Linux) or simple Python wrapper that logs `open()` for write to stderr.
- Run repro; inspect `trace.log` for writes whose target path resolves outside the current worktree.
- Common bug pattern: script using `git rev-parse --show-toplevel` from a context where cwd isn't the worktree root, OR using `os.path.dirname(os.path.abspath(__file__))` and walking up to a hardcoded marker that finds the wrong repo.

**For test X**:
- Add `conftest.py`-level autouse fixture that monkey-patches `pathlib.Path.write_text`, `pathlib.Path.write_bytes`, `open(..., 'w')`, `open(..., 'wb')`. Each call logs target path + caller's `inspect.stack()` frame.
- Run pytest; inspect log for writes outside the worktree dir.

**Phase 4 output**: a specific code path (file:line) where the cross-worktree write happens. Becomes the basis for Phase 5.

## Phase 5 — Targeted fix

Fix shape depends on Phase 4 finding.

**If `update_readme.py` (or another pre-commit script) writes outside the worktree**:
- Replace `Path(__file__).parent.parent` walks with `git rev-parse --show-toplevel` from cwd (pre-commit's contract guarantees cwd = worktree root).
- OR add explicit `--repo-root` arg.
- Regression test: invoke the script from a worktree with cwd set; assert it never opens a file outside the worktree dir tree.

**If snapshot tests write to absolute paths**:
- Audit `installer/tests/e2e/test_snapshots_*.py` for `Path("/home/raul/...")` or `os.environ["HOME"]`-derived paths.
- Replace with pytest's `tmp_path` fixture or `Path(__file__).parent` (relative-to-test).
- Regression test: a `conftest.py` autouse fixture that wraps `Path.write_text` and asserts target path is inside `tmp_path` or `Path(__file__).parent`.

**If `uv` cache / venv leaks**:
- Audit pre-commit + uv invocation lines for `UV_CACHE_DIR` setting.
- Each worktree should set `UV_CACHE_DIR` to a worktree-local path (e.g. `.uv-cache/` in worktree root, NOT shared `~/.cache/uv`).
- Regression: smoke test that `uv run` in worktree A doesn't write to worktree B's `.uv-cache/`.

**Common fix structure**:
1. Phase 0 repro script becomes the regression test (CI gate, or at minimum a `scripts/repro/735-*.sh` runnable manually).
2. Document cause + fix in wiki `[[worktree-rebase-artifact]]` "Status" section: change "Cause not root-caused" → "Root cause: <description>. Fixed in commit <SHA>."
3. Decision-log entry per managed rule 20 documenting bug + fix rationale.

## Parallel track — Workaround codification

Ships REGARDLESS of investigation outcome. Independent of Phases 1-5; can run first (smaller) or last.

**Update wiki `[[parallel-impl-orchestration]]` recipe** "Known speed bumps" section:

Change the `worktree-rebase-artifact` entry from "git restore . then rebase" to a more careful procedure:

```
Before each sequential rebase step:
  git status --porcelain
  if non-empty:
    LOG warning: "unstaged content in <worktree> — possible 735 artifact"
    SHOW diff to user via AskUserQuestion: [Discard | Investigate | Abort]
      user picks "Discard" → git restore . → retry rebase
      user picks "Investigate" → halt; user resolves manually
      user picks "Abort" → halt batch
```

**Update `proj:parallel-batch-execute` skill Phase 5 step 1**: same `git status --porcelain` check + AskUserQuestion gate.

**Implementation files**:
- `~/.claude/wiki/pages/concepts/parallel-impl-orchestration.md` (Known speed bumps section)
- `plugins/proj/skills/parallel-batch-execute/SKILL.md` (Phase 5 step 1 prose)

**Constraint**: per managed rule 8 (destructive ops need consent), NEVER auto-restore preemptively. Always AskUserQuestion before `git restore .`.

## Risks

| Risk | Mitigation |
|---|---|
| Phase 1 reproduces (git internals) | Escalate to user before deeper rabbit hole; may end up filing upstream git bug. |
| Time-box hit (no repro after Phase 3) | Document evidence; fall back to workaround codification only; revisit when more batch data accumulates. |
| Phase 5 fix breaks other workflows | Phase 0 repro script as regression test; full proj suite run catches collateral damage. |
| Workaround codification adds friction | Default to log-only when rare; AskUserQuestion only when frequent. Tune via field test. |
| `strace` not available / permission denied (Phase 4) | Fall back to Python-level wrapper for pre-commit scripts; pytest fixture-level wrapping for tests. |
| Phase 0 fixture doesn't reproduce because real bug needs subagent dispatch (parallel writes via Agent tool) | Spec doesn't fully isolate from this. If Phases 1-3 all pass but real batches still fail, add Phase 3.5: replicate with parallel `Agent()` dispatches, not just sequential bash loop. |

## Validation

**Per phase**:
- Phase 0: script runs idempotently; produces deterministic state log.
- Phase 1: `--no-verify` repro pass = no artifact in 3 sequential rebases.
- Phase 2: per-hook bisection identifies (or rules out) culprit.
- Phase 3: per-test bisection identifies (or rules out) culprit.
- Phase 4: trace log shows specific cross-worktree write OR confirms no such write happens (in which case investigation is inconclusive — escalate).
- Phase 5: regression test passes; full proj suite passes; manual repro of original bug condition no longer produces artifact.

**Parallel track**: `git status --porcelain` check appears in both wiki + SKILL prose; AskUserQuestion options are exactly [Discard | Investigate | Abort].

## Cross-references

- Wiki: [[worktree-rebase-artifact]] (current state — "cause not root-caused")
- Wiki: [[parallel-impl-orchestration]] (recipe with the "Known speed bumps" section to update)
- Wiki: [[parallel-orchestration-boundary-issues]] (calls out 735 as recurring 2/2)
- Wiki: [[parallel-git-races]] (different failure mode — distinct from 735)
- Skill: `plugins/proj/skills/parallel-batch-execute/SKILL.md` (Phase 5 step 1 to update)
- Sibling todo 736 (just shipped): the parallel-batch-execute skill that 735's findings will harden.
- Pre-commit config: `/home/raul/projects/claude-project-manager/.pre-commit-config.yaml`
- Suspect script: `scripts/update_readme.py`
- Suspect tests: `installer/tests/e2e/test_snapshots_*.py`
- Trigger session: 2026-04-25 (D+E + Batch A clusters; this session's 735 brainstorm)

## Open questions (deferred — non-blocking for plan)

1. Should Phase 0 repro script be a CI-gated test, or stay manual? Decision: manual for v1; revisit if root cause identifies a regression-prone code path.
2. If Phase 1 reproduces, do we file upstream git bug? Out of scope for v1; user decides at escalation point.
3. Does the `parallel-batch-execute` skill's Phase 5 step 1 update warrant a SKILL version bump? Probably not — it's a prose tightening, not a behavior change. Confirm during writing-plans.
