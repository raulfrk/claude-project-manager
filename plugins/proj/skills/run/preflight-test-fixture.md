# Preflight Test Fixture

This file documents a synthetic todo used to verify the expanded preflight
(`/proj:run` Phase A.5 structural checks and Phase A.5b adversarial agents).

**Success contract**: running `/proj:run <fixture-id> --careful` against this
fixture must produce **exactly 3 BLOCKING findings** across structural and
adversarial phases. Any more or fewer indicates a regression.

## Fixture todo spec

Create a new todo in a disposable project (or use a dedicated `preflight-test`
project) with `preflight_version: 2` and the following content files.

### requirements.md (fixture)

```markdown
# Requirements: Add a robust, scalable ingestion pipeline

## Goal

Build a robust, scalable ingestion pipeline that handles incoming events
and routes them appropriately.

## Acceptance Criteria

- [ ] Users can ingest data smoothly.
- [ ] The system handles load well.
- [ ] Errors are handled properly.

## Edge Cases

- Empty input.
- Large input.

## Out of Scope

- Retry logic.

## Testing Strategy

1. Unit tests for the router.
2. Integration test against a fake queue.
```

### research.md (fixture)

```markdown
# Research

## Recommended Approach

Use a message queue and a worker pool. This is a standard architecture that
scales well. Several libraries exist; pick whichever is most popular.

## Approach Options

1. Use a queue.
2. Use a different queue.

## Risks

Unknown.
```

## Known defects (exactly 3 BLOCKING findings expected)

### Defect 1 — Vague language (check 6, BLOCKING)

The Goal section contains `robust` and `scalable`, both in the expanded
vague-phrase list. The Acceptance Criteria section contains `smoothly`,
`well`, and `properly` — but these are not in the hardcoded list (excluded
by policy as practical engineering prose). The **Goal-section match on
`robust`+`scalable`** fires check 6 with a BLOCKING finding (multiple
tokens in one section count as a single BLOCKING finding for this check).

> NOTE: if the vague-phrase list is retuned to include additional terms
> from the fixture, update this section to keep the expected count at 3.
> The canonical list (23 terms) lives in `plugins/proj/skills/run/SKILL.md`
> under Phase A.5 check 6.

### Defect 2 — Missing failure mode (check 10, BLOCKING)

The "Edge Cases" section lists only "Empty input" and "Large input" — neither
is an explicit failure mode (error path, network failure, permission error,
concurrency, timeout, missing file, invalid input). Check 10 fires BLOCKING.

### Defect 3 — Research file-path anchor (check 8, BLOCKING)

research.md "Recommended Approach" and the (absent) "Key Dependencies"
section reference no file paths in the repo. Check 8 fires BLOCKING.

## Non-BLOCKING findings expected (informational, not part of the contract)

These are expected but do NOT count toward the contract of 3 BLOCKING findings:

- Check 9 (research option distinctness) — "Use a queue" vs "Use a different
  queue" is not distinct by library/tool/placement/data-flow. WARNING.
- Check 7 (acceptance criterion verifiability) — criteria lack file paths,
  function names, test names, or numeric thresholds. This may also fire
  BLOCKING depending on tuning; if it does, the fixture is failing the
  "exactly 3" contract and the test must fail loudly so the list can be
  retuned.
- Adversarial agents (Ambiguity, Completeness, Research Validation) will
  likely add WARNING-level findings, which do not count toward the BLOCKING
  total.

## Running the fixture

```console
# Create the fixture todo (manually, via todo_add) in a disposable project
# with preflight_version: 2

/proj:run <fixture-id> --careful --steps preflight

# Expected output: exactly 3 BLOCKING findings listed in the preflight table
# Any deviation indicates a regression — investigate before shipping.
```

## Self-validation checklist (run before shipping the expanded checks)

- [ ] Run check 6 against all 8 tier-0 requirements.md files (todos 487,
      503, 504, 505, 507, 508, 509, 510). Must produce **0 false positives**.
      If any tier-0 requirements.md fires check 6, retune the vague-phrase
      list and re-run.
- [ ] Run the full preflight suite against the fixture. Must produce
      **exactly 3 BLOCKING** findings (defects 1, 2, 3 above).
- [ ] Confirm adversarial-agent findings are WARNING-level and not
      polluting the BLOCKING count.
