# Post-605 Cleanup Spec

## Context

The 605 overhaul consolidated 9 plugins into 6 (folded sandbox into proj, zoxide into worktree, analyse into proj). Code changes are complete and CI-green, but docs, installer, git state, and test coverage lagged behind. This cleanup brings everything into sync.

## Commit 1: Fix README auto-generation

**Problem:** `scripts/update_readme.py:143` writes to marker `plugins-table` but `README.md:54,64` uses markers `plugins-start`/`plugins-end`. Script never matches, table stays stale.

**Fix:**
- `README.md:54` — rename `<!-- AUTO:plugins-start -->` to `<!-- AUTO:plugins-table-start -->`
- `README.md:64` — rename `<!-- AUTO:plugins-end -->` to `<!-- AUTO:plugins-table-end -->`
- `scripts/update_readme.py:54-59` — update `generate_plugins_table()` to produce `[name](plugins/name/)` links (matching existing manual table format) instead of plain `**name**`
- Run the script once to verify it populates from marketplace.json (6 plugins, all 5.0.0)

**Files:** `README.md`, `scripts/update_readme.py`

## Commit 2: Sync docs with 5.0.0

### docs/architecture.md

- Line 9: "7 plugins" → "6 plugins"
- Lines 13-18: Update all version numbers to 5.0.0. Remove any row for deleted plugins if present.

### docs/plugins.md

- Line 20: `**Version**: 2.6.0` → `**Version**: 5.0.0` (worktree)
- Line 89: `**Version**: 3.0.1` → `**Version**: 5.0.0` (proj)
- Lines 125-126: Remove `todo_add_child` and `todo_batch_add_children` rows (merged into `todo_add(parent=...)`)
- Lines 135-136: Remove `todo_block` and `todo_unblock` rows (merged into `todo_update(blocked_by_set=...)`)
- Line 194: `proj_todoist_full_sync()` → `proj_sync(integration="todoist")`
- Line 195: `proj_trello_full_sync()` → `proj_sync(integration="trello")`
- Line 198: `proj_jira_full_sync()` → `proj_sync(integration="jira")`

**Files:** `docs/architecture.md`, `docs/plugins.md`

## Commit 3: Fix installer stale refs

### installer/app.py

- Line 114: Remove `"sandbox"` from `_PROJ_PLUGINS` set. This set determines which plugins trigger the wizard's proj.yaml configuration flow. Sandbox tools are now part of proj and don't need a separate entry.
- Note: `installer/screens/wizard.py:19` already excludes sandbox — only app.py is stale.

### installer/tests/test_main.py

- Line 607: Remove `assert "sandbox" in InstallerApp._PROJ_PLUGINS` (matches the app.py change).

### installer/wizard_specs.py

- Line 172: `label="Enable sandbox integration"` → `label="Enable settings.json management (sandbox tools)"`
- Line 180: `label="Enable zoxide integration"` → `label="Enable zoxide frecency tracking"`

Config keys (`sandbox_integration`, `zoxide_integration`) and defaults.yaml stay unchanged — they're valid hook conditions.

**Files:** `installer/app.py`, `installer/wizard_specs.py`, `installer/tests/test_main.py`

## Commit 4: Git hygiene (no code commit)

- Delete all 122 local branches fully merged into dev: `git branch --merged dev | grep -v '^\*\|dev\|main' | xargs git branch -d`
- Prune 4 stale worktrees: `git worktree remove` for todo-475.23, batch3-todoist-sync, todo-601, todo-605.6
- Preserve 6 active worktrees (604.1-604.5, 626)

## Commit 5: Test coverage todos

Create proj todos for critical-path test coverage (proj + router = 60 files):

### proj plugin (44 files, split into 3 batches)
- **proj-lib** (20 files): sql_todos.py, sql_archive.py, sql_meta.py, sql_decisions.py, db.py, state.py, storage.py, models.py, enums.py, ids.py, migration.py, tracking_git.py, resilience.py, backoff.py, retry.py, router_health.py, sockets_cleanup.py, sandbox/models.py, sandbox/storage.py, sandbox_helpers.py
- **proj-tools-core** (12 files): todos.py, projects.py, content.py, config.py, context.py, context_injection.py, git.py, decisions.py, knowledge.py, explore.py, digest.py, migrate.py
- **proj-tools-sync** (12 files): sync.py, todoist_full_sync.py, trello_sync.py, trello_full_sync.py, trello_migration.py, jira_sync.py, jira_full_sync.py, perms_sync.py, perms_grant.py, _perms_common.py, sandbox.py, tracking_git.py

### router plugin (16 files, split into 2 batches)
- **router-lib** (10 files): constants.py, dag.py, conditions.py, template.py, discovery.py, _types.py, models.py, http_client.py, storage.py, trello_label_validation.py
- **router-tools** (6 files): verify.py, fire.py, sync.py, recovery.py, invocations.py, registry.py

5 todos total, each representing a batch. Priority: medium. Implementation deferred.

## Verification

After all commits:
- `python scripts/update_readme.py` exits 0 (README up to date)
- `grep -r "sandbox" installer/ --include="*.py"` shows no stale plugin refs (only updated labels)
- `git branch --merged dev | wc -l` ≈ 2 (just dev and main)
- `git worktree list` shows only main repo + 6 active worktrees
- CI green on push
