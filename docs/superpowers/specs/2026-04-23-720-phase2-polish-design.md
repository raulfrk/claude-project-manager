# Phase 2 Polish Bundle (720) Design

**Date:** 2026-04-23
**Todo:** 720
**Branch (planned):** `feat/720-phase-2-polish`

---

## Goals

Tighten `/proj:save` step 10b prose and close 2 test coverage gaps from Phase 2 of the Karpathy CPM integration (todo 699). Single PR, single commit. Pure follow-up — no behavioral change beyond reworded prose; no API change; no managed-block change.

## Non-goals

- No managed-block edits.
- No new MCP tools or skills.
- No `notes_append` API change (signature unchanged from b558e5c).
- No `/proj:save` behavioral change beyond prose rewording (semantics identical).
- No additional Phase 2 test categories beyond M4 + M5 (that scope was bounded in the original code review).

## Background

Phase 2 of the Karpathy integration (todo 699) shipped at commits `b477784` + `b558e5c`. Code review of `b477784` flagged 2 important issues (race + heading ambiguity, fixed in `b558e5c`) and 4 minor follow-ups (M2-M5) that were deferred and tracked in todo 720. This spec resolves todo 720.

**M2 — caveman polish in step 10b**: `(light prompt, single dismiss)` parenthetical and `Optionally also call` filler can be tightened.
**M3 — gating logic clarity in step 10b**: zero-vs-≥1-decision conditions listed sequentially can be collapsed to a positive-skip guard followed by the negative branch.
**M4 — missing tool-layer test for `op="decision"` `content_first_line` round-trip**: storage tests cover the format; the MCP tool layer test only asserts `op="note"`.
**M5 — missing non-monkeypatched test for legacy `notes_append` `content_first_line` derivation**: the existing legacy-path test monkeypatches `storage.append_note` so the real first-line-of-text derivation in `notes_append` is never exercised.

## Design

### M2 + M3 — `/proj:save` step 10b rewrite

**Current** (`plugins/proj/skills/save/SKILL.md` lines 76-80):

```
**10b.** Decision-log reminder (light prompt, single dismiss):
 - Step 8 logged 0 decisions (no Key Decisions in synthesis) → ask via `AskUserQuestion`: "No decisions logged this session. Any to capture before save?" Options: Yes / No.
 - Yes → user supplies decision text; call `mcp__proj__notes_append(heading=<short title>, op="decision", text=<full text>)`. Optionally also call `mcp__proj__proj_decision_log` if user marks it as a structured A/B pick.
 - No → proceed silently to step 11.
 - Step 8 logged ≥1 decision → skip reminder.
```

**Proposed**:

```
**10b.** Decision-log reminder:
 - Step 8 logged ≥1 decision → skip 10b.
 - Zero decisions → ask via `AskUserQuestion`: "No decisions logged this session. Any to capture before save?" Options: Yes / No.
   - Yes → user supplies text; call `mcp__proj__notes_append(heading=<short title>, op="decision", text=<full text>)`. If user marks as A/B pick: also call `mcp__proj__proj_decision_log`.
   - No → proceed silently to step 11.
```

Diffs:
- Drop `(light prompt, single dismiss)` parenthetical (M2)
- Reorder: positive-skip guard first, then negative branch w/ Yes/No nested under it (M3)
- Drop `(no Key Decisions in synthesis)` parenthetical (M2 — implied by step 8)
- Tighten `decision text` → `text` (M2 — redundant)
- Convert `Optionally also call X if user marks Y` → `If user marks Y: also call X` (M2 — fronts the conditional, removes `Optionally also` filler)

### M4 — new tool-layer test for `op="decision"` `content_first_line`

Append to `plugins/proj/server/tests/test_context.py` inside the existing `TestNotesAppendHeadingConvention` class. Match the existing async + `mcp_app` fixture pattern used by sibling tests in that class.

```python
async def test_notes_append_content_first_line_uses_decision_op(tmp_cfg, mcp_app):
    """When op='decision', content_first_line uses 'decision | ' separator (tool-layer assertion).
    Storage tests cover the on-disk format for op='decision'; this closes the tool-layer gap.
    """
    name = "myapp"
    _setup_project_with_todos(tmp_cfg, name, Path(tmp_cfg.tracking_dir).parent, todos=[])
    state.set_session_active(name)

    result = await call_tool(mcp_app, "notes_append", text="A vs B chose A", heading="DB choice", op="decision")
    parsed = json.loads(result)
    import re
    assert re.match(
        r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] decision \| DB choice",
        parsed["content_first_line"],
    ), f"content_first_line wrong shape for op='decision': {parsed['content_first_line']!r}"
```

### M5 — new non-monkeypatched legacy-path test

Append to same class as M4. Crucial: do NOT monkeypatch `storage.append_note` — exercise the real first-line derivation logic in `tools/context.py:notes_append`.

```python
async def test_notes_append_legacy_no_heading_first_line_from_text(tmp_cfg, mcp_app):
    """When heading is None, content_first_line equals first line of text (backward compat).
    No storage monkeypatch — exercises the real first_line derivation in notes_append.
    """
    name = "myapp"
    _setup_project_with_todos(tmp_cfg, name, Path(tmp_cfg.tracking_dir).parent, todos=[])
    state.set_session_active(name)

    result = await call_tool(mcp_app, "notes_append", text="first line of body\nsecond line\nthird line")
    parsed = json.loads(result)
    assert parsed["content_first_line"] == "first line of body", parsed["content_first_line"]
```

## Testing

- `cd plugins/proj/server && uv run pytest tests/test_context.py -k "notes_append" -v` — expect 6 passing (4 prior + 2 new).
- Full proj-server suite (`uv run pytest`) — expect no regression. Phase 2 test count was 1873 passing on b558e5c; this PR should land at 1875.
- Manual eyeball of `/proj:save` SKILL.md after edits to confirm step numbering still parses (10 → 10b → 11).

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Helper signature drift: `_setup_project_with_todos` or `call_tool` evolved since Phase 2 | Low | Medium | Implementer reads the existing `TestNotesAppendHeadingConvention` class first + matches the pattern verbatim. |
| Step 10b parsed by some downstream tool that depends on exact old wording | Trivial | Trivial | No parsers consume `/proj:save` SKILL.md prose; only Claude reads it as instructions. |
| New tests flaky on slow CI (real `datetime.now()` in M4 regex assertion) | Trivial | Low | Regex tolerates any HH:MM combination; only the format must match, not the value. |

## Implementation footprint

- Modify: `plugins/proj/skills/save/SKILL.md` (1 multi-line Edit op replacing the entire step 10b block)
- Modify: `plugins/proj/server/tests/test_context.py` (append 2 test functions inside existing test class)
- 1 commit on `feat/720-phase-2-polish`, FF-merge to dev
- No managed-block change, no README change, no MCP tool change

## Resolved decisions (from brainstorm Q&A)

- **Scope**: all 4 items (M2 + M3 + M4 + M5) included.
- **Packaging**: single PR, single commit.
- **Step 10b wording**: as proposed above.
- **Test placement**: M4 + M5 inside the existing `TestNotesAppendHeadingConvention` class in `tests/test_context.py`, matching the async + `mcp_app` pattern of sibling tests.

## Open questions

None. Spec fully specified for implementation.

## References

- Phase 2 commits: `b477784` (initial impl) + `b558e5c` (race + heading ambiguity fix)
- Phase 2 code-review minor findings (M2-M5) tracked in todo 720
- `/proj:save` SKILL.md current state: `plugins/proj/skills/save/SKILL.md:76-80`
- Phase 2 test class: `plugins/proj/server/tests/test_context.py::TestNotesAppendHeadingConvention`
