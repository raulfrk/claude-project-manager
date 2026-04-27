# scripts/

Utility scripts for claude-project-manager development and maintenance.

---

## audit-685-687-rule.sh

**Purpose**: Audit git worktrees for potential rule-685/687 misparses.

Managed CLAUDE.md rule 13 (historically rule 685, refined by 687) instructs Claude to
run `git fetch origin` then conditionally `git reset --hard origin/<base>` (or `<base>`
if the local branch has unpushed commits) immediately after `wt_create`. If Claude
misparsed the conditional or skipped the reset, the worktree's HEAD may sit behind
`origin/<base>` by commits that already existed at creation time.

This script scans all worktrees under a root directory and flags any where
`origin/<base>` is ahead of HEAD — a heuristic signal that the post-`wt_create` sync
may have been skipped.

**Detection heuristic**: `git rev-list HEAD..origin/<base>` after `git fetch`. Count > 0 → flag.

**Exit codes**:
- `0` — no anomalies (all worktrees current or SKIPped/WARNed with explanation)
- `1` — one or more worktrees flagged as potentially stale

**Usage**:

```bash
# default: scans $HOME/worktrees
./scripts/audit-685-687-rule.sh

# explicit root
./scripts/audit-685-687-rule.sh /path/to/worktrees

# via env var
WORKTREES_ROOT=/path/to/worktrees ./scripts/audit-685-687-rule.sh
```

Expected layout: `WORKTREES_ROOT/<repo>/<branch>/` — e.g. `~/worktrees/cpm/feat-123-my-feature`.

**Output markers**:
- `OK` — worktree is current with upstream
- `SKIP` — upstream ref not found (branch not yet pushed, or non-remote branch) — not an anomaly
- `WARN` — fetch failed (offline, missing remote) — not counted as anomaly
- `FLAG` — worktree is behind upstream — potential rule misparse

**Limitations**:
- Heuristic only: a worktree intentionally behind its base (e.g. mid-rebase) will also flag.
- Does not check whether the stale state existed at creation time or developed later.
- Detached-HEAD worktrees are SKIPped.

**Suggested invocation**: run manually after a batch of parallel worktree agents completes,
or schedule weekly via `/schedule` to catch drift over time.

---

## check_deps.py

Validates that all plugin Python dependencies are consistent across the monorepo.

## _gather_shared_version_state.py

Pre-conftest data gatherer: collects staged `_shared/*.py` files, HEAD vs staged
`pyproject.toml` versions, and each `uv.lock`'s pinned `claude-hook-transport` version
into a JSON document on stdout. Pipe to conftest:

```bash
python scripts/_gather_shared_version_state.py | conftest test --namespace cpm.shared_version_cascade --policy policies/ -
```

Replaces the prior `check_shared_version.py` validator (logic now in
`policies/shared_version_cascade.rego`).

## migrate-hooks.py

One-time migration script for converting legacy `hooks/` plugin data to the `router/` format.

## presync.sh

Pre-syncs all plugin venvs so `uv` doesn't timeout during MCP server startup. Run once
after cloning or after adding new deps.

```bash
./scripts/presync.sh
```
