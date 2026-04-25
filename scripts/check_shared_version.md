# check_shared_version: validate-only vs auto-regen rubric

## Current behavior

`scripts/check_shared_version.py` is a pre-commit hook with two validation stages:

1. **Version-bump check** — when any `plugins/_shared/*.py` file is staged (excluding
   `plugins/_shared/tests/`), the hook reads `plugins/_shared/pyproject.toml` from both
   the staged index and `HEAD`. If the version is unchanged, it fails with an instruction
   to bump the version before committing.

2. **Lockfile-drift check** — when the version *did* bump, the hook reads each of the 9
   declared `uv.lock` files from the staged index and verifies the pinned
   `claude-hook-transport` version matches the new `_shared` version. Any mismatch (wrong
   version, missing file, or file not staged) is listed as drift, and the hook fails with:

   ```
   Run `just sync` at repo root to regenerate all uv.lock files, then
   `git add <paths>` and commit again.
   ```

The hook does **not** modify files. It validates and exits. All remediation is manual.

## Why auto-regen was rejected (2026-04-23)

During the design phase for todo 692
(`docs/superpowers/specs/2026-04-23-687-691-692-700-bundled-cleanups-design.md` §4.1 +
§7), auto-regen was considered as an alternative: the pre-commit hook would detect a
`_shared` version bump, run `just sync` automatically to regenerate all `uv.lock` files,
re-stage the updated lockfiles, and succeed in a single commit.

Rejected for three reasons:

1. **Higher complexity** — the hook must execute `just sync`, handle subprocess failures
   and timeouts, then re-stage files mid-commit. More failure modes vs. a read-only
   validator.
2. **Slower commits** — `just sync` across 9 lockfiles takes several seconds; every
   `_shared` bump would incur this cost inside the commit flow.
3. **Masking surprises** — auto-staging generated files hides the fact that lockfiles
   changed. A validate-only hook forces the developer to inspect and stage those changes
   consciously, matching the existing project culture of explicit git operations.

Validate-only was chosen as the lighter-touch, dogfood-able alternative. The spec note:
*"692 validates; doesn't automate. If devs repeatedly hit the new check, consider a
genuine auto-regen pre-commit hook (rejected option from brainstorm)."*

## Revisit triggers

Reconsider auto-regen if **any** of:

- **≥3 drift-blocked commits** across **≥2 contributors** within 30 days — indicates the
  manual `just sync` + re-stage loop is causing recurring friction, not a one-off
  oversight.
- **CI flakes** attributable to post-merge lockfile drift — e.g., a merged commit that
  passed pre-commit locally but triggered `uv.lock` cleanup commits on CI, signaling the
  hook alone is insufficient.
- **Onboarding friction reports** from new contributors hitting the validator — if the
  `just sync` hint is unclear or the workflow is unfamiliar, auto-regen may reduce
  cognitive load for first-time contributors more than it risks.
- **`just sync` becomes slow (>30 s)** such that the "fail → sync → re-stage → commit"
  round-trip becomes painful — at that point the latency cost argument against auto-regen
  weakens.

## Auto-regen alternative (if revisited)

High-level sketch:

1. Pre-commit hook detects `_shared` version bump (same as current stage 1).
2. On bump: run `just sync` at repo root (regenerates all 9 `uv.lock` files).
3. Re-stage the updated lockfiles via `git add <LOCKFILES>`.
4. Exit 0 — commit proceeds with regenerated lockfiles already staged.

**Estimated complexity**: medium. Key failure modes to handle:

- `just sync` subprocess error (missing `just`, missing `uv`, network issues) — must
  surface the error clearly rather than silently failing or succeeding with stale files.
- Staging order — re-staging must happen *after* the sync and *before* the commit
  finalizes; standard pre-commit hook execution order supports this.
- Partial sync — if only some lockfiles update, the hook must validate all expected paths
  are correctly pinned before exiting 0.

Implementation entry point: replace the `_check_lockfiles_pin_new_version` call in
`main()` with a `_sync_and_stage_lockfiles()` call guarded by a feature flag (e.g.,
`AUTO_REGEN=1` env var or a config key in `pyproject.toml`), allowing a gradual rollout.

## Decision authority + cadence

- **Owner**: project maintainer (raulfrk).
- **Revisit cadence**: ad-hoc when triggers fire (no scheduled review).
- **Cross-ref**: `docs/superpowers/specs/2026-04-23-687-691-692-700-bundled-cleanups-design.md`
  §692 for the original decision context and §7 for the follow-up note on auto-regen.
