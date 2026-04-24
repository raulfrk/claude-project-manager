# D + E Cluster: Parallel Implementation Design

**Status**: draft
**Owner**: raul
**Date**: 2026-04-25
**Todos covered**: 723, 728, 726, 714, 715
**Workflow**: light per-todo plans inline (no separate spec docs); per-todo worktree; subagent-driven impl; serialized FF-merges; single push at end. No revdiff.

## Context & Motivation

Five backlog todos clustered into two themes — D (installer / wizard UX) and E (infra / dev-experience). Each is independently scoped, low-coupling, and small enough to ship in parallel without merge conflict risk. Goal: ship all five in a single coordinated push to dev, minimising per-todo overhead while keeping reviewer discipline intact.

Per user direction (brainstorm 2026-04-25):
- Per-todo worktree, agents spawned in this session, controller-side coordination.
- Implementer model: **sonnet** (not haiku — these touch real code paths, including installer + Python; sonnet handles the integration surface better).
- **Single push at end** after all 5 FF-merge to local dev → one CI run for the batch.
- No revdiff for spec or per-todo plans (text review only).
- Wiki query each todo's area before drafting plan (research enrichment).

## Wiki Research Summary

Pre-drafting research from `/wiki:query` on each topic (BM25 + page reads). Findings inform the per-todo plans below.

| Todo | Key wiki references |
|---|---|
| 723 | [[wiki-config-flags]] (4-file map; `bootstrap_pending` flag), [[wiki-plugin]] |
| 728 | [[ppid-walk-ancestry-detection]] (matcher regex + `CPM_CLAUDE_CODE_CMDLINE_MATCHER` env var override), [[installer-fixes-657-658]] (precedent for installer wizard step additions) |
| 726 | [[plugin-structure]] (pyproject layout); `plugins/_shared/pyproject.toml` addopts is the file in question |
| 714 | [[post-wt-create-remote-sync]] (full impl detail of rule 685 + 687 refinement; lives in `plugins/_shared/claudemd/managed_section.md`) |
| 715 | [[bundled-cleanups-687-691-692-700]] (todo 692 shipped `scripts/check_shared_version.py` — the validate-only pre-commit; auto-regen was the rejected option) |

## Orchestration Architecture

```
Controller (this session)
├── Setup phase (sequential)
│   ├── 5× wt_create + sync (one worktree per todo)
│   └── Per-todo plans inline in this spec (already complete)
├── Implementation phase (parallel, fan-out)
│   ├── Implementer 723 (sonnet, run_in_background=true)
│   ├── Implementer 728 (sonnet, run_in_background=true)
│   ├── Implementer 726 (sonnet, run_in_background=true)
│   ├── Implementer 714 (sonnet, run_in_background=true)
│   └── Implementer 715 (sonnet, run_in_background=true)
├── Review phase (parallel as each implementer signals DONE)
│   ├── Spec reviewer per todo (haiku)
│   ├── Quality reviewer per todo (superpowers:code-reviewer subagent)
│   └── Re-review loop on findings
├── Merge phase (sequential)
│   ├── FF-merge 723 → dev (local only, no push)
│   ├── FF-merge 728 → dev (local only)
│   ├── FF-merge 726 → dev (local only)
│   ├── FF-merge 714 → dev (local only)
│   ├── FF-merge 715 → dev (local only)
│   └── git push origin dev (single push, single CI run)
├── Cleanup phase (parallel)
│   ├── 5× wt_remove
│   └── 5× git branch -d
└── Bookkeeping
    ├── Watch CI in background
    └── Mark todos done (batch-complete)
```

**Concurrency safety**: each worktree owns its own files; no two implementers touch the same file (verified per per-todo plan below). Reviewers run in parallel with no shared state. Merge phase serializes — only the controller calls `git merge --ff-only` against the main repo's dev branch.

**Push deferral**: per user direction, all 5 land on local dev before any push. CI fires once on the final push.

## Per-Todo Plans

Each plan is intentionally tight (~30-50 lines). Full task discipline (read → edit → verify → commit) is in the implementer prompt, not duplicated here. The per-todo plan section captures: goal, files, decision, success criteria.

---

### Todo 723 — Wiki installer wizard partial-init bug

**Branch**: `feat/723-wiki-wizard-init-fix`

**Goal**: Resolve the deadlock where the installer wizard writes `~/.claude/wiki.yaml` + `~/.claude/wiki/config.yaml` + subdirs but skips seeding `index.md` + `log.md`, then `/wiki:init` refuses (config exists) and `/wiki:bootstrap` refuses (empty index). User must manually call `wiki_index_rebuild` + `wiki_log_append` to escape.

**Decision** (pick one of the 3 fix directions from todo notes; implementer plans the choice based on smallest installer surface):

- **Preferred**: Installer-side seed. After writing configs, the wizard calls the wiki MCP's `wiki_index_rebuild` + `wiki_log_append(action="init", title="installer-seeded", body="{}")`. Single point of fix; subsequent skill flows see a properly-initialised wiki.
- **Fallback A**: `/wiki:init` detects partial-init state (wiki.yaml exists AND index.md missing) and completes the seed. Pushes the recovery into the user-invoked skill.
- **Fallback B**: `/wiki:bootstrap` auto-seeds empty wikis before its current "stop on empty index" guard fires. Aligns with bootstrap's existing role but blurs init/bootstrap responsibilities.

**Files**:
- Likely: `installer/installer/<wiki-related-step>.py` + tests under `installer/tests/`.
- If Fallback A: `plugins/wiki/skills/init/SKILL.md`.
- If Fallback B: `plugins/wiki/skills/bootstrap/SKILL.md`.

**Wiki context**: [[wiki-config-flags]] documents the 4 config files. `bootstrap_pending: true` is the wizard-set marker; whatever fix lands should set it to `false` once the wiki is fully seeded.

**Success criteria**: Fresh install via wizard → user can run `/wiki:bootstrap` (or `/wiki:query` immediately) without manual `wiki_index_rebuild`. Add a regression test (installer test or wiki integration test) that exercises the fresh-install path end-to-end and asserts `index.md` exists post-wizard.

---

### Todo 728 — Wizard prompt to kill stale Claude Code sessions on clean install

**Branch**: `feat/728-wizard-kill-stale`

**Goal**: After a clean install / reinstall via the installer wizard, detect other running `claude` processes and prompt the user to kill them so they pick up the new plugin code (per the 2026-04-24 decision: "plugin reinstall blast radius is new sessions only").

**Files**:
- `installer/installer/<post-install-step>.py` (new step or extension of existing post-install confirmation).
- Tests in `installer/tests/`.

**Implementation sketch**:
1. After "install confirmed" message + before "all done" message, run `psutil.process_iter(['pid', 'cmdline'])`.
2. Apply matcher regex (default `(?:^|/)claude(?:\s|$)`; allow `CPM_CLAUDE_CODE_CMDLINE_MATCHER` env override for parity with [[ppid-walk-ancestry-detection]]).
3. Filter out the wizard's own ancestor PIDs (walk `os.getppid()` chain via psutil, exclude the chain).
4. If matches: prompt `"N other Claude Code sessions are running with cached plugin versions. Kill them so they pick up the new install? [y/N]"` (default no).
5. On `y`: SIGTERM each, `wait` with timeout, fall back to SIGKILL if still alive.
6. On `n` or no matches: continue to "all done" silently.

**Wiki context**: [[ppid-walk-ancestry-detection]] documents the existing matcher; reuse the same pattern + env var. [[installer-fixes-657-658]] is the pattern for adding new installer wizard steps (Rich-only TUI per [[rich-only-tui]]).

**Success criteria**: New install with 2 dummy `sleep` processes spoofing claude cmdline → wizard detects + prompts. Confirm wizard's own PID chain is excluded (no self-kill). Test via `installer/tests/` with mocked psutil.

---

### Todo 726 — `_shared` pyproject coverage config blocks isolated module runs

**Branch**: `feat/726-shared-coverage-config`

**Goal**: Stop `--cov-fail-under=80` from firing on aggregate of all `--cov` targets when only one module's tests are run, which exits 1 even though the targeted module is well-covered.

**Files**:
- `plugins/_shared/pyproject.toml` (addopts).

**Decision** (pick one of 4 from todo notes):

- **Preferred**: Document the workaround inline + leave config alone. Add a comment in `pyproject.toml` near `addopts` pointing readers at `--no-cov` for targeted runs, and a one-line note in `plugins/_shared/README.md` (or `CONTRIBUTING.md` if it exists) explaining: "isolated module test runs need `--no-cov` because `--cov-fail-under=80` aggregates across all `--cov=<pkg>` targets". Smallest change; preserves CI's strict gate.
- **Alternative**: Split per-package thresholds via `[tool.coverage.run]` + per-source thresholds. More invasive; matrix grows with each new shared package.

**Wiki context**: [[plugin-structure]] confirms `_shared` is the canonical home for cross-plugin Python packages. The aggregate-cov behavior is intentional for CI but noisy locally.

**Success criteria**: Workaround documented in pyproject.toml + README. Local dev workflow doc updated if applicable. No code change to test files.

---

### Todo 714 — 687 rule complexity: monitor for parse failures, promote to wt_create hook if needed

**Branch**: `feat/714-687-rule-monitoring`

**Goal**: Light observability for rule 685 + 687 (the `wt_create`-then-conditional-reset workflow rule). Currently lives as managed CLAUDE.md prose; if Claude misparses the conditional, no signal exists.

**Decision** (minimal deliverable per user "all 5 in scope" direction):

- Add a one-line observability hook in the worktree plugin's `wt_create` (server-side) that logs which reset branch was taken. NOT enforcing the rule programmatically — just emitting a structured log line so future misparses are visible.
- Specifically: after `wt_create` returns, the controller (Claude) runs the rule. The `wt_create` MCP tool itself doesn't run the rule. So observability needs to be on the *Claude side*, which we cannot instrument from inside `wt_create`.
- **Revised deliverable**: write a small standalone script `scripts/audit-685-687-rule.sh` that scans recent worktree creation timestamps + their post-create branch state, flags worktrees where the reset clearly went wrong (e.g. `git log` shows the worktree at a stale base SHA when origin had advanced). Run weekly via [[/schedule]] or manually. Docs the script's purpose + invocation in `scripts/README.md`.

**Files**:
- `scripts/audit-685-687-rule.sh` (new).
- `scripts/README.md` (extend with the new script's usage).

**Wiki context**: [[post-wt-create-remote-sync]] documents the rule + the 687 refinement. Rule prose lives in `plugins/_shared/claudemd/managed_section.md`. [[bundled-cleanups-687-691-692-700]] confirms 687's design intent.

**Success criteria**: Script runs cleanly against current worktree state, exits 0 when no anomalies, exits 1 + lists suspect worktrees when anomalies present. Manual smoke run by implementer; output captured in commit message.

---

### Todo 715 — `_shared` uv.lock auto-regen evaluation rubric

**Branch**: `feat/715-shared-uv-lock-evaluation`

**Goal**: Document the trigger conditions for flipping todo 692's validate-only pre-commit hook into an auto-regen hook. Per todo notes, no code change unless drift incidents accumulate.

**Decision** (minimal deliverable):

- Add an evaluation rubric doc next to the existing validator: `scripts/check_shared_version.md` (sibling of `scripts/check_shared_version.py`). Documents:
  1. Current behavior (validate-only).
  2. Trigger conditions for revisiting (≥3 drift commits across ≥2 contributors in 30 days, OR CI flake from post-merge lockfile drift).
  3. Auto-regen alternative (rejected in 692; can be reactivated).
  4. Decision authority + revisit cadence.

**Files**:
- `scripts/check_shared_version.md` (new).

**Wiki context**: [[bundled-cleanups-687-691-692-700]] is the canonical history of 692's validator + why auto-regen was rejected initially. Reference it from the rubric doc.

**Success criteria**: Doc exists; future maintainer reading the validator script can find the rubric and decide whether to revisit. No code change to the validator itself.

---

## Setup Sequence (controller, before fan-out)

For each todo (5×):

1. `wt_create(repo_label="cpm", branch="<branch>", base_branch="dev")` → returns `worktree_path`.
2. `cd <worktree_path> && git fetch origin && git rev-list origin/dev..dev` → confirm 0 (FF-mergeable) → `git reset --hard origin/dev`.
3. (For 723 + 728 only): `cd installer && uv sync --all-groups` to ensure dev deps in venv (avoid the fresh-worktree-venv issue from 5.1.4 work).

Total setup: ~30 seconds × 5 worktrees, possibly parallel via Bash.

## Implementer Dispatch Pattern

For each worktree, dispatch one implementer with this template:

```
Agent({
  description: "Impl <todo-id>",
  subagent_type: "general-purpose",
  model: "sonnet",
  run_in_background: true,
  prompt: <full per-todo plan section above + work directory + commit message template + report format>
})
```

Background dispatch lets the controller fan out without blocking. Each implementer signals DONE → controller proceeds to spec + quality review for that todo.

## Review Pattern

Per the 727 precedent (subagent-driven-development):
- After each implementer DONE → spec compliance reviewer (haiku, fast verification of "did they build what was specified").
- After spec ✅ → code quality reviewer (`superpowers:code-reviewer` subagent).
- Re-review loop on findings.
- Mark task complete only when both reviews pass.

## Merge + Push Sequence

After all 5 implementers + reviews complete:

1. `cd /home/raul/projects/claude-project-manager && git pull --ff-only origin dev` (sanity).
2. `git merge --ff-only feat/723-wiki-wizard-init-fix`.
3. `git merge --ff-only feat/728-wizard-kill-stale`.
4. `git merge --ff-only feat/726-shared-coverage-config`.
5. `git merge --ff-only feat/714-687-rule-monitoring`.
6. `git merge --ff-only feat/715-shared-uv-lock-evaluation`.
7. **Single** `git push origin dev` → one CI run.
8. `gh run watch <id> --exit-status` (background).

Order rationale: lowest-risk first (715 doc-only, 726 doc + comment) on the *original* schedule; here we're merging in todo-id order which is fine because none touch overlapping files (verified per plan above).

## Cleanup

- `wt_remove` × 5 (parallel via tool calls).
- `git branch -d` × 5 (sequential, fast).
- Mark todos complete via `mcp__plugin_proj_proj__todo_complete` (5 ids — use batch path).

## Risks

- **Implementer 723 deadlock w/ wiki state**: if the implementer tries to test the fix by running the wizard against the user's real `~/.claude/`, it could mutate live wiki state. Implementer prompt must direct testing into `tmp_path` (pytest fixture) or a sandboxed `HOME`.
- **Implementer 728 SIGKILL accident**: if the matcher pattern is too loose, the wizard could kill non-Claude processes. Test must include a non-claude process in the mock psutil result and assert it's not in the kill list.
- **Implementer 714 deliverable ambiguity**: the deliverable is a script, but its "correct output" depends on real worktree state. Implementer should test against synthetic worktree state in a test, not the user's actual worktrees.
- **Implementer 715 doc drift**: rubric doc could go stale if the validator script changes. Add a one-line cross-ref in `check_shared_version.py` header pointing at the `.md` sibling.
- **Merge order surprise**: if any per-todo edit accidentally touches a shared file (e.g. someone edits `plugins/_shared/pyproject.toml` in 726 AND 715), merges 2-5 may conflict. Per-plan file lists are disjoint, but reviewers should sanity-check.

## Out of scope

- Changing the wt_create MCP tool (rule 685/687 stays a workflow rule per [[post-wt-create-remote-sync]] design rationale).
- Building the auto-regen hook for uv.lock (715 is rubric doc only).
- Closing 714/715 as no-ops (user opted to ship minimal deliverables).

## Acceptance

- All 5 worktrees produce passing implementer + spec + quality reviews.
- All 5 FF-merge cleanly to local dev.
- Single push lands all 5 on origin/dev.
- CI green on the merged commit.
- 5 worktrees + branches cleaned.
- 5 todos marked done via batch complete.
