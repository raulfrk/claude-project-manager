# Caveman Adoption — Reflections

Reflections on the `dev-caveman` experiment. Companion to
[caveman-bench.md](caveman-bench.md) (runbook) and todo 519 (decision
log in `~/projects/tracking/claude-project-manager/todos/519/`).

## What the experiment tests

Whether Claude output compression via presentation-layer rules
("caveman mode") produces meaningful efficiency gains (tokens,
latency, context usage) without degrading task outcomes.

The hypothesis: a large chunk of Claude's output is filler prose that
the user already discards while reading. Removing it at the source
saves tokens on **both** sides of the wire (output tokens billed,
context consumed on next turn).

The null hypothesis: compression drops load-bearing qualifiers,
introduces ambiguity, or makes error messages harder to parse, and the
user reverts within a session.

## What works

- **Perimeter is cleanly enforced.** The CI guard + pre-commit hook
  reject the `cpm:caveman` marker on `main` / `dev` and no-op on
  `dev-caveman`. Experiment contamination is mechanically prevented,
  not documented-and-hoped.
- **Sidecar backup is reversible.** The magic-header sidecar lets
  restore preserve user edits outside the managed markers. A user who
  customized their CLAUDE.md before trying caveman mode gets their
  customizations back after rollback.
- **Branch-aware sync is opt-in.** Plain `git checkout dev-caveman`
  does not mutate `~/.claude/CLAUDE.md`. The installer wizard is the
  explicit sync point. This matches the D519.3 decision and avoids
  the worst failure mode (home-directory mutation on every branch
  switch).
- **Idempotence everywhere.** Re-running the installer wizard on the
  same branch produces no changes. Re-running restore produces no
  changes. Re-running backup preserves the earliest snapshot.

## What doesn't work (yet)

- **No automated SKILL.md conversion.** The original 519 plan proposed
  a bulk rewrite of ~45 SKILL.md files via a sub-team. That was
  descoped to the user-invoked `/caveman:compress` skill path (see
  stub note below). As a result, most skills on `dev-caveman` still
  ship with default prose; caveman compression is only visible in the
  managed section of the global CLAUDE.md.
- **No benchmark harness.** The runbook describes a manual diff
  procedure. A dedicated script that runs the same todo end-to-end on
  both branches and produces a comparable token/latency report would
  be more trustworthy than ad-hoc manual runs.
- **Load-bearing qualifier detection is manual.** The compression
  rules list categories that must stay verbatim, but there is no
  linter that fails if a caveman rewrite drops one. Enforcement
  relies on the author noticing.

## Stub: 519.4 SKILL.md conversion

SKILL.md caveman conversion is performed via `/caveman:compress` by
the user; see `docs/caveman-bench.md` section "Running /caveman:compress".

The original 519.4 proposed a batch rewrite via a sub-team. That was
replaced with user-invoked conversion because:

- batch rewrites lose per-skill judgment about which qualifiers are
  load-bearing
- the user wants to approve each conversion deliberately, not review
  a 45-file diff after the fact
- `/caveman:compress` already exists as a user-facing skill; no new
  infrastructure needed

## Open questions

- Does caveman mode actually reduce tokens in practice, or does
  Claude expand the compressed output back into prose during
  downstream reasoning?
- Do load-bearing qualifiers survive in real skills, or does the
  compression drift over a long session?
- Is the `*caveman*` glob the right trigger, or should it be a
  config flag decoupled from branch name?
- If the experiment graduates, what's the migration path — merge the
  installer changes (sidecar, splice logic, helper) without the
  `dev-caveman`-specific content, or maintain a separate variant
  selector keyed on a config flag?
- Should the installer wizard prompt the user before rewriting
  `~/.claude/CLAUDE.md` when it detects a caveman-branch checkout,
  or is the current "installer runs => sync happens" contract
  enough friction?

## Observations

Populate this section as benchmark runs accumulate. Each entry should
record: todo ID exercised, branch, token count, wall-clock duration,
and any qualitative notes about rule drift or output readability.

_(empty — no benchmark runs yet)_

## Decision log pointer

Full requirements, Q&A transcript, and decision history for this
experiment are in todo 519:
`~/projects/tracking/claude-project-manager/todos/519/`

Key decisions:
- **D519.1**: perimeter via CI guard + pre-commit, not documentation
- **D519.2**: sidecar backup with magic header for reversible global
  CLAUDE.md mutation
- **D519.3**: installer-wizard-only sync, no branch-checkout auto-sync
- **D519.4 (revised)**: no batch SKILL.md rewrite; user-invoked
  `/caveman:compress` path instead
