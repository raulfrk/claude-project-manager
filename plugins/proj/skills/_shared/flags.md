---
shared: flags
---
> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

## Flag Parsing

Parse from $ARGUMENTS:

- `--fast` / `--careful` — mutually exclusive, last wins, default `--careful`
- `--no-verify` — skip verification phase
- `--no-interactive` — demote BLOCKING→WARNING, auto-continue, log via `notes_append`
- `--no-tasks` — disable all TaskCreate calls
- `--from <step>` — slice step list starting at given step
- `--iter N` — repeat prep phases N times (default 1)
- `--max-parallel N` — override max_parallel ceiling
- `--with-adversarial-review` — re-enables Phase A.5b + C0.5b adversarial agents (off by default)
- `--resume` — resume from most recent checkpoint

Removed flags (emit error):
- `--balanced` → ERROR: "balanced removed, use --careful"
- `--paranoid` → ERROR: "paranoid removed, use --careful --max-parallel 1"

Derive:
```
tasks_enabled = "--no-tasks" not in ARGUMENTS
adversarial_review_enabled = "--with-adversarial-review" in ARGUMENTS
```

Quality level: if no flag, call `mcp__proj__config_load` → read `config.quality_level`, default `--careful` if unset/unrecognized.

**Former `--paranoid` behavior**: `--careful --max-parallel 1` (sequential exec).

## Quality Level Parameter Mapping

| Parameter | --fast | --careful (default) |
|-----------|--------|---------------------|
| gate_override | auto-execute (tag-immune) | full-review |
| verification_mode | skip | enhanced |
| max_parallel | 30 | 10 |
| satisfaction | skip (auto-complete) | per-todo |
| preflight | skip | enabled |
| preflight_structural | skip | enabled |
| pre_execute_preflight | skip | enabled |
| refine | skip | auto-enabled (per iteration) |
| overlap_action | auto-proceed | auto-serialize |

**Recommended cap**: 10 for CPU-bound/API-rate-limited. `--fast` ceiling 30 for I/O-bound; override via `--max-parallel` or `config.team_mode.max_agents`.

## Flag Compatibility Checks

Validate before proceeding:

- `--no-verify --careful` → WARNING: "--no-verify overrides --careful's enhanced verification." Verification skipped.
- `--no-verify --fast` → Redundant (no-op).

## Per-Todo Quality (batch mode)

`effective_quality(todo_id) = per_todo_quality.get(todo_id, quality_level)` — per-todo annotation if present, else batch-level.

Tag-immune upgrade: if annotated `fast` + tag `security`/`breaking-change`/`migration` → silently upgrade to `careful` + warn.

> All quality-level gates in batch mode MUST use `effective_quality(todo_id)`, never bare `quality_level`.
