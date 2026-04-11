# Caveman Mode Runbook

Operational guide for the `dev-caveman` experimental branch of
`claude-project-manager`.

Caveman mode is a **presentation-layer compression** of Claude output:
drop articles, filler, pleasantries, hedging; fragment sentences; short
synonyms; pattern `[thing] [action] [reason]. [next step].` Security and
safety rules, commit messages, code, frontmatter, paths, and load-bearing
qualifiers are always preserved in full prose.

Caveman mode is **never** a rule override. If a rewrite would drop a
qualifier that changes meaning, the rewrite is wrong — revert to full
prose for that passage.

## Perimeter

The experiment lives entirely on `dev-caveman`. Two guards enforce this:

- `.github/workflows/caveman-guard.yml` — CI job that rejects the
  `cpm:caveman` marker and the caveman-mode header on any push to `main`
  or `dev`. No-op on `dev-caveman`.
- `.pre-commit-hooks/caveman-guard.sh` — pre-commit hook that rejects
  the same markers locally. Runs on every commit; no-op when the current
  branch is `dev-caveman`.

`dev-caveman` **must never merge** to `dev` or `main`. If the experiment
graduates, graduation is a deliberate content migration (not a merge).

## Branch switching

Caveman mode is keyed on the current git branch AND the active project
name. Both must be true for the variant to activate:

- project name is exactly `claude-project-manager`
- current branch matches the glob `*caveman*` (env var `CPM_CAVEMAN_BRANCH`
  can override the glob for tests)

Branch detection uses `git symbolic-ref --short HEAD`, not
`git rev-parse`, so a detached HEAD fails cleanly instead of returning
the literal `HEAD` and tripping the glob.

### Installer wizard sync

Branch detection and managed-section rewriting happen **only** when the
user runs the installer wizard. Plain `git checkout` does NOT silently
mutate `~/.claude/CLAUDE.md` — that would be a surprising home-directory
mutation on every branch change (D519.3).

To apply the caveman variant after switching branches:

```bash
cd ~/projects/claude-project-manager
git checkout dev-caveman
# re-run the installer wizard; it detects the branch and rewrites
# ~/.claude/CLAUDE.md to include the caveman append
uv run python -m installer
```

To revert:

```bash
git checkout dev            # or main
uv run python -m installer  # installer restores the default variant
```

## Sidecar mechanism

When the caveman variant is installed, the installer first backs up the
current `~/.claude/CLAUDE.md` to a sidecar file:

- path: `~/.claude/CLAUDE.md.pre-caveman`
- first line: magic header `# CPM-CAVEMAN-BACKUP v1 <ISO-8601 UTC timestamp>`
- body: the verbatim pre-caveman CLAUDE.md content

The sidecar is **idempotent**: if a valid sidecar already exists when
`_backup_global_claudemd_for_caveman` runs, the earlier sidecar is
preserved unchanged. This is intentional — the earliest pre-caveman
snapshot is what we want to keep, not the most recent caveman-state file
in a caveman-to-caveman re-run.

If the sidecar exists but the first line does NOT start with the magic
header prefix, the backup raises `ValueError` rather than clobber an
unknown file. Same contract on restore.

### Restore preserves user edits

`_restore_global_claudemd_from_caveman` does NOT paste the sidecar body
back into place. It reads the current CLAUDE.md, splits it into
`(before_managed, managed, after_managed)` using the managed markers,
and replaces only the managed block with the default variant. Any user
edits outside the managed markers survive verbatim.

After restore the sidecar is left in place so repeated restores are
safe no-ops.

## CI guard and pre-commit behavior

**On `main` and `dev`:**
- pre-commit rejects any commit containing `cpm:caveman` or the
  caveman-mode header marker
- CI `caveman-guard.yml` fails the build with a clear error message on
  push or PR

**On `dev-caveman`:**
- pre-commit guard detects the branch and no-ops
- CI guard detects the branch and passes

**Testing the guards:**

```bash
# on dev, intentionally add a banned marker and attempt to commit
git checkout dev
echo "# cpm:caveman" >> /tmp/test-file
git add /tmp/test-file
git commit -m "should fail"  # pre-commit rejects

# on dev-caveman, the same content commits cleanly
git checkout dev-caveman
git commit -m "should pass"  # no-op
```

Do NOT test by pushing to `main` / `dev`.

## Adding a caveman-aware skill

SKILL.md conversion to caveman style is NOT automated. The original 519
plan proposed a bulk rewrite via a sub-team; the revised plan uses the
user-invoked `/caveman:compress` skill instead. See
[caveman-adoption.md](caveman-adoption.md) for the rationale.

### Running `/caveman:compress`

The user invokes `/caveman:compress <path-to-skill.md>` interactively in
a Claude Code session while on `dev-caveman`. The skill:

1. reads the target SKILL.md
2. rewrites the body using the caveman compression rules (preserving
   the verbatim list: security/safety, code/commits, frontmatter/paths,
   load-bearing qualifiers)
3. writes the result back in place
4. leaves a commit for the user to stage and push on `dev-caveman`

No batch mode — one skill per invocation, deliberate approval each time.

## Benchmarking caveman vs default

The experiment is about whether compressed output meaningfully reduces
token usage and session duration without degrading task success. No
automated benchmark harness ships in this commit; benchmarking is a
manual exercise:

1. pick a representative task that runs end-to-end on both branches
   (e.g. `/proj:run <todo-id>` with a medium-complexity todo)
2. run the task on `dev` with a fresh Claude Code session; record token
   count from the status bar and wall-clock duration
3. switch to `dev-caveman`, re-run the installer wizard so the global
   CLAUDE.md picks up the caveman append, start a fresh session, re-run
   the same task on the same todo ID
4. diff the resulting branches: is the implementation equivalent? did
   any rule get lost in compression? did the token count drop?

Record findings in `docs/caveman-adoption.md` under "Observations".

## Rollback

If caveman mode causes problems on `dev-caveman`:

1. `git checkout dev` (or `main`)
2. `uv run python -m installer` — installer detects non-caveman branch,
   runs restore path, rewrites `~/.claude/CLAUDE.md` to default variant
   while preserving user edits outside the managed markers
3. sidecar at `~/.claude/CLAUDE.md.pre-caveman` stays in place for
   audit; delete it manually if desired
