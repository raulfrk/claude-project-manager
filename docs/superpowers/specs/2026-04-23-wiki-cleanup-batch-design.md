# Wiki Cleanup Batch — Design

**Date**: 2026-04-23
**Branch**: `feat/wiki-cleanup-batch`
**Worktree**: `/home/raul/worktrees/cpm/feat-wiki-cleanup-batch`
**Base**: `dev` @ `d583e05`
**Scope**: bundled cleanup of wiki-plugin code-review follow-ups (todos 706, 707, 708, 709) + cross-plugin e2e test (709 item 4) + one pre-existing test-collection fix (709 item 5 partial).
**Out of scope**: todo 710 (managed CLAUDE.md rewrite for wiki+superpowers awareness — being worked in a separate session; do not touch `plugins/_shared/claudemd/managed_section.md`).

## Motivation

Wiki plugin shipped end-to-end across 5 phases (61 commits, FF-merged to dev @ `f052a6f`). Each phase final code review surfaced minor follow-up items, captured as todos 706/707/708/709 with `auto-added` tag. Bundling them into a single PR avoids 4 trickle PRs while keeping scope reviewable: all items are non-blocking, low-risk, and traceable to specific review findings.

The cross-plugin e2e test (709 item 4) is included to lock in a regression net-net for the proj↔wiki integration before further wiki work proceeds. Pre-existing `test_todo_add_e2e_hooks.py` collection error (unrelated to wiki) is bundled because it presents as noise in the same `pytest` runs we'll execute as part of verification.

## Drift from todo notes (reconciled by Explore agent)

Mapping inspection on dev @ `d583e05` revealed three items that no longer apply:

- **708 item 3 (ghost entries in `allowed-tools`)**: no ghost entries in `ingest/SKILL.md` or `bootstrap/SKILL.md`. SKIP.
- **709 item 3 (`mcp__plugin_wiki_wiki__wiki_scope_detect` missing from `/proj:save` allowed-tools)**: already present at line 4. SKIP.
- **707 item 4 (`bootstrap_completed` vs `bootstrap_pending` typo)**: spec uses both for distinct purposes; needs investigation to confirm typo vs. distinct fields. Convert to a doc-only investigation step in commit 4.

## Commits

Per-todo organization, 8 commits total. Each commit message uses cpm convention `<type>(<scope/todo>): <subject>`.

### Commit 1 — `fix(wiki/706): phase-1 review follow-ups`

| Item | File | Change |
|------|------|--------|
| 706.1 FastMCP import harmonization | `plugins/wiki/server/server/tools/index.py` | Switch from `if TYPE_CHECKING + # type: ignore[name-defined] on register()` to the `if TYPE_CHECKING ... else: from mcp.server.fastmcp import FastMCP # noqa: TC002` pattern used by `tools/page.py`, `tools/log.py`, `tools/links.py`. Drop the type:ignore on the `register` signature. |
| 706.2 TOCTOU on `wiki_page_write` upsert | `plugins/wiki/server/server/tools/page.py` lines 91-110 | Move the read-then-hash no-op-detection block from before `with storage.wiki_lock(wiki_dir):` to inside the lock. Preserve the early-return semantics for true no-op writes. |
| 706.5 Log body trailing-content assertion | `plugins/wiki/server/tests/test_log.py` `test_append_preserves_prior_entries` | Add an assertion that the body content of the first appended entry is intact (not truncated) after the second append. |
| 706.6 Spec §6 `slug` consistency | `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §6 | Verify all tool-param tables use `slug`. Explore reports already consistent — if true, drop this item from the commit. |

### Commit 2 — `test(wiki/706): defensive-path coverage`

Net-new tests; no production-code changes.

| Target | New test |
|--------|----------|
| `plugins/wiki/server/server/lib/storage.py:44-47` (atomic_write cleanup on `os.replace` failure) | One test: monkeypatch `os.replace` to raise; assert temp file removed. |
| `plugins/wiki/server/server/lib/index.py` `_first_summary_line` lines 35, 37, 39 | Three small assertions: empty body → empty string; body starts w/ heading → skip heading; all-heading body → empty return. |
| `plugins/wiki/server/server/lib/models.py:91, 94` `Page.scope` single-string branch + category no-`pages` branch | Two assertions: scope as plain string parses to single-element list; category dict missing `pages` defaults to empty. |
| `plugins/wiki/server/server/lib/profile.py:67-68` malformed-YAML raise path | One test: write broken YAML, assert specific exception raised. |

Coverage target: maintain or improve the wiki baseline of 90.62%.

### Commit 3 — `refactor(wiki/707): consolidate _write_page test helper`

| File | Change |
|------|--------|
| `plugins/wiki/server/tests/conftest.py` | Extend the `_write_page` helper signature to accept `body: str = "body"` as an optional kwarg. Default keeps current behavior. |
| `plugins/wiki/server/tests/test_search.py` line 13 | Remove the local `_write_page(wiki_dir, category, slug, body, **fm_extras)` definition; use the conftest helper. |
| `plugins/wiki/server/tests/test_lint_broken_links.py` line 12 | Remove local `_write_page_with_body(wiki_dir, category, slug, body, **fm_extras)`; use conftest helper. |
| `plugins/wiki/server/tests/test_page_list.py` (706 item 3) | Verify import still works (helper already in conftest per Explore — no change needed unless callsite uses old signature). |

Verification: full `cd plugins/wiki/server && uv run pytest tests/ -v` must remain 171/171 green.

### Commit 4 — `docs(wiki/707): spec + docstring polish`

Doc/comment-only changes.

| Item | File | Change |
|------|------|--------|
| 707.2 BM25 oversampling caveat | `plugins/wiki/server/server/tools/search.py` `wiki_search_bm25` docstring | Append: `"Filters applied to top limit*3 BM25 hits when category/tags/scope set; may miss relevant pages in very large wikis with sparse target categories."` |
| 707.3 Lint return-shape doc | `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §6 | Update the `wiki_lint_schema` row to list `path` + `invalid_fields` in addition to `missing_fields`. Update `wiki_lint_stale` row to list `path` + `age_days` in addition to existing keys. |
| 707.4 `bootstrap_completed` vs `bootstrap_pending` resolution | `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §4.3 (lines 167 + 205) | Read both spec mentions. Decision tree: (a) if both fields exist with distinct purposes (Explore's hypothesis), document the distinction inline in the spec; (b) if one is a stale typo, remove the typo. Implementation reference: `bootstrap_pending` is the live field per code. If unresolved in 15 minutes, defer via a fresh todo and SKIP this item from the commit. |

### Commit 5 — `fix(wiki/708): skill polish`

| Item | File | Change |
|------|------|--------|
| 708.1 promote scope-detect | `plugins/wiki/skills/promote/SKILL.md` | Add `mcp__plugin_wiki_wiki__wiki_scope_detect` to allowed-tools (line 4). Add a step 1: informational call to `wiki_scope_detect` (impact small since promote operates on explicit slug; documents intent). |
| 708.2 Idempotency intent docs | `plugins/wiki/skills/ingest/references/source-readers.md` + `dedup-protocol.md` | Add a one-sentence note that subagent-level dedup (matching `sources[*].ref` on pages) is intentional defense-in-depth on top of the skill-level `wiki_log_read` check (ingest step 4). |
| 708.4 IDEMPOTENCY block alignment | `plugins/wiki/skills/ingest/references/subagent-prompt.md` lines 73-76 | Verify the source-ref matching logic mirrors the skill-level check. If divergent, align. If already aligned, drop this item from the commit. |
| 708.5 `references/` convention note | `plugins/wiki/README.md` | Reinforce the existing `references/` subfolder convention as the preferred pattern when SKILL.md content exceeds ~250 lines (already documented per the last-session decisions; verify wording is durable). |
| 708.6 Bootstrap proj-aware → todo 705 | `plugins/wiki/skills/bootstrap/SKILL.md` proj-aware section | Add a user-facing note that proj-aware enumeration depends on the active-project being persisted (todo 705 / file-backed `~/.claude/proj-session.yaml`); session-only setups will fall back to standalone mode. |
| 708.7 `find` portability | `plugins/wiki/skills/bootstrap/SKILL.md` (`find` invocation introduced as the must-fix replacing `ls <dir>/**/*.md`) | Audit the `find` invocation for BSD vs GNU divergence. Use only flags safe on both: `-name`, `-type f`, `-maxdepth`. If any GNU-only flag (`-printf`, `-regextype`, `-ipath`) is used, refactor. |
| 708.3 ghost entries | n/a | SKIP — Explore confirmed no ghosts. |
| 708.8 Phase-4 scope-detect refactor | n/a | DEFER — depends on todo 705 resolution. |

### Commit 6 — `fix(wiki/709): phase-4a follow-ups`

| Item | File | Change |
|------|------|--------|
| 709.1 `WikiSync.auto_sync` field | `plugins/proj/server/server/lib/models.py` line 277 | Drop the `auto_sync: bool` field per YAGNI (Explore: zero readers). **Pre-flight check**: grep `auto_sync` across `plugins/proj/server/server/lib/config.py`, `~/.claude/proj.yaml` template defaults, all serialization paths. If the field is written by `config_init` or appears in any user-facing default, downgrade to "document intent in dataclass docstring + spec §4.3" instead of dropping. |
| 709.2 `scope.py` type-ignore audit | `plugins/wiki/server/server/tools/scope.py` lines 35, 40, 43 | Re-audit each `# type: ignore[...]` comment with `uv run basedpyright`. Remove ignores where isinstance narrowing or proper typing fixes the underlying issue. Keep ignores that are genuinely justified (with a one-line comment explaining why). |
| 709.6 `notes_append` JSON return doc | `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md` §8.1 | Document the `notes_append` JSON return shape (`{status, project_name, content, content_first_line, message}`) and the `${content_first_line}` template substitution used by the router hook. |
| 709.3 wiki_scope_detect in save allowed-tools | n/a | SKIP — already present per Explore. |
| 709.5 pre-existing failures | n/a | Partial: only the test-collection fix (commit 8). The `test_context.py::TestClaudemdRefreshManaged*` cohort is left to the parallel 710 session. |

### Commit 7 — `test(wiki/709): cross-plugin e2e CI integration`

New automated test asserting the proj↔wiki round-trip end-to-end.

**Goal**: replace the existing manual shell smoke (`plugins/wiki/scripts/smoke_*` or equivalent) with an automated pytest that exercises the full router path: `notes_append` (proj plugin) → `router_fire_tool` (router plugin) → `wiki_log_append` (wiki plugin) → assertion that the wiki log entry exists with the expected content.

**Test location**: `plugins/_shared/tests/test_wiki_proj_e2e.py` (new file). Aligns with the existing `_shared/tests/` exclusion already in `check_shared_version.py` per commit `d583e05`.

**Implementation choice (resolved during writing-plans)**: pick between (a) subprocess: spawn each plugin's MCP server via `uv run python -m server`, drive via Unix-socket JSON-RPC client; (b) in-process: import each plugin's `register` function, build a single FastMCP test instance, exercise via FastMCP's `Client` test helper. (b) is faster + has no port conflicts but does not exercise the actual socket transport. Recommend (a) for true e2e; deferred to plan phase.

**CI matrix**: confirm the existing matrix entry covers `plugins/_shared/tests/`. If not, add one. Per the 2026-04-23 decision (memory): "new plugins must explicitly add a row to `.github/workflows/ci.yml::jobs.test.strategy.matrix.include`". This is not a new plugin but a new test file under `_shared/`; verify CI picks it up.

### Commit 8 — `fix(proj): test_todo_add_e2e_hooks ModuleNotFoundError`

Pre-existing collection error: `ModuleNotFoundError: No module named 'hook_dispatch'`.

**Investigation**: `grep -rn "sys.path" plugins/proj/server/tests/` to find the existing path-shim pattern (likely in `conftest.py`). Apply the same pattern to make `hook_dispatch` resolve. Most likely a `sys.path.insert(0, "<plugins_root>/_shared/hook_dispatch")` line missing from this test's conftest scope.

**Verification**: `cd plugins/proj/server && uv run pytest tests/test_todo_add_e2e_hooks.py --co -q` returns no collection error.

## Architecture / boundaries

No architectural changes. All items are surface-level fixes within existing plugin boundaries:

- **wiki plugin** internals: commits 1, 2, 3, 4, 5, 6 (excluding 6's models.py touch).
- **proj plugin** `lib/models.py`: commit 6 item 1 only (one-field cleanup).
- **shared tests**: commit 7 (new file under `plugins/_shared/tests/`).
- **proj plugin** test infrastructure: commit 8 (path-shim fix).

The persistence/synthesis boundary established in the wiki spec (`MCP = pure persistence; synthesis in skills`) is unaffected. The cross-plugin file-I/O boundary (`wiki_scope_detect` reads `~/.claude/proj-session.yaml` directly, no MCP coupling) is unaffected.

## Test plan

Per commit:

| Commit | Local verification |
|--------|--------------------|
| 1 | `cd plugins/wiki/server && uv run pytest tests/test_page.py tests/test_log.py -v` |
| 2 | `cd plugins/wiki/server && uv run pytest tests/ --cov=server --cov-report=term-missing` — coverage ≥ 90.62% baseline |
| 3 | `cd plugins/wiki/server && uv run pytest tests/ -v` — all 171/171 green |
| 4 | manual read-through; no test impact |
| 5 | YAML lint each touched SKILL.md frontmatter; smoke `/wiki:promote` against the test wiki dir |
| 6 | `cd plugins/proj/server && uv run pytest && uv run basedpyright` (must stay green); grep audit for `auto_sync` references before drop |
| 7 | new test runs green locally + in CI |
| 8 | `cd plugins/proj/server && uv run pytest tests/test_todo_add_e2e_hooks.py --co -q` clean |

**Pre-merge gate**: `just check` from worktree root (full lint + type + test across all plugins).

## Merge strategy

Per cpm convention (memory `feedback_624_merge_convention.md`): no PR; FF-merge to dev; CI runs on push.

```bash
# Inside /home/raul/worktrees/cpm/feat-wiki-cleanup-batch:
git fetch origin
git rebase origin/dev          # rebase commit chain; resolve conflicts inline
just check                     # full validation
git push origin feat/wiki-cleanup-batch  # optional: push branch for visibility / backup

# In main repo /home/raul/projects/claude-project-manager:
git fetch origin
git checkout dev
git pull --ff-only origin dev
git merge --ff-only feat/wiki-cleanup-batch
git push origin dev
gh run watch                   # watch CI
```

**Coordination with parallel 710 session**: do not touch `plugins/_shared/claudemd/managed_section.md` or `plugins/proj/server/tests/test_context.py::TestClaudemdRefreshManaged*`. If a rebase conflict surfaces in those files post-710-merge, defer to 710's resolution.

**Cleanup**: after green CI, `mcp__plugin_worktree_worktree__wt_remove` on the worktree path; complete todos 706, 707, 708, 709 via `mcp__plugin_proj_proj__todo_complete`.

## Risks + mitigations

| Risk | Mitigation |
|------|------------|
| `WikiSync.auto_sync` field is read by config init/serialization paths missed by Explore | Pre-flight grep across `plugins/proj/server/`, config templates, user `~/.claude/proj.yaml`; downgrade to "document intent" if any reader found. |
| Conftest `_write_page` extension breaks tests using the existing helper | Default `body: str = "body"` keeps existing call sites unchanged; full pytest run gates the commit. |
| TOCTOU fix in `wiki_page_write` changes observable behavior of no-op writes (e.g. timing, lock contention metrics) | Existing `test_page.py` covers no-op semantics; verify all tests stay green; add an assertion if the no-op return contract is under-tested. |
| E2E test design unresolved (subprocess vs in-process) | Defer to writing-plans phase; spec captures the intent + CI placement. |
| `find` syntax in commit 5 item 7 may need testing on macOS BSD | Restrict to portable flags (`-name`, `-type f`, `-maxdepth`); manual review of any change. |
| Rebase against an active dev (parallel 710 session) creates conflicts | Coordinate via the explicit out-of-scope list; rebase late in the day after 710 lands if both happen same-day. |

## Acceptance criteria

- All 8 commits land on `feat/wiki-cleanup-batch`.
- `just check` green from the worktree root.
- FF-merge succeeds without coercion (no `--allow-unrelated`, no force).
- CI green on `dev` after push (`gh run watch` reports success).
- Todos 706, 707, 708, 709 marked complete in proj.
- Worktree removed.
- Todo 710 untouched.

## References

- Wiki plugin spec: `docs/superpowers/specs/2026-04-21-karpathy-wiki-plugin-design.md`
- Phase final-review todos: 706, 707, 708, 709 in `~/projects/tracking/claude-project-manager/todos.yaml`
- Branch convention memory: `~/.claude/projects/-home-raul-projects-claude-project-manager/memory/feedback_624_merge_convention.md`
- CI matrix decision (2026-04-23): noted in last-session decisions log; matrix is not auto-derived from `plugins/<name>/server/`.
