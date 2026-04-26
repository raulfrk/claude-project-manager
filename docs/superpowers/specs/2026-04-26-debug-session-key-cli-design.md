# debug-session-key CLI Subcommand — Design

**Date**: 2026-04-26
**Status**: approved
**Tracks todo**: 778

## Problem

Post-779 fix, the only signal that the session-key resolver has drifted is the silent `proj_session_context` "no active project" failure. If a future regression breaks the resolver, debugging requires manually walking the process tree (`pgrep -af claude-bin`), inspecting `~/.claude/proj-session.yaml`, and `/proc/<pid>/environ` for EXECPATH. There's no single command that prints what the resolver sees.

## Goal

Add a CLI subcommand `python -m server.cli debug-session-key` that prints, in one shot:

1. `CLAUDE_CODE_EXECPATH` value (or `<unset>`).
2. Resolved session key (`get_claude_session_key()` output).
3. Current process pid + ppid.
4. Full ancestor chain w/ `pid`, `realpath(exe)` for each (matches what the resolver walks).
5. Relevant `proj-session.yaml` slot for the resolved key (if exists).

Plain-text output, human-readable. Run from anywhere (no project context required).

## Non-goals

- JSON output. Caveman-friendly text only; if a future need surfaces, add a `--json` flag then.
- Touching `proj-session.yaml`. Read-only diagnostic.
- Including the slug-collision history or ingest log. Out of scope; this is purely a session-key resolver diagnostic.
- Wrapping in a proj plugin SKILL.md. CLI subcommand is sufficient.

## Architecture

Single-file change: `plugins/proj/server/server/cli.py` — add a `debug-session-key` subparser + `cmd_debug_session_key()` function.

### Subparser registration (in `main()`)

```python
debug_skey = sub.add_parser("debug-session-key")
# No additional args; reads from environment.
...
elif args.command == "debug-session-key":
    cmd_debug_session_key()
```

### Function

```python
def cmd_debug_session_key() -> None:
    """Print resolver state for diagnosing session-key issues.

    Output:
        CLAUDE_CODE_EXECPATH: <value or '<unset>'>
        Resolved session key: <pid string>
        Process: pid=<own_pid> ppid=<own_ppid>
        Ancestor chain (immediate-first):
          pid=<X> exe=<realpath>
          pid=<Y> exe=<realpath>
          ...
        proj-session.yaml slot for key '<resolved>': <yaml fragment or '<missing>'>
    """
    import psutil

    from session_key import session_key as sk

    execpath = os.environ.get("CLAUDE_CODE_EXECPATH", "<unset>")
    resolved = sk.get_claude_session_key()
    own_pid = os.getpid()
    own_ppid = os.getppid()

    print(f"CLAUDE_CODE_EXECPATH: {execpath}")
    print(f"Resolved session key: {resolved}")
    print(f"Process: pid={own_pid} ppid={own_ppid}")
    print("Ancestor chain (immediate-first):")
    try:
        for ancestor in psutil.Process().parents():
            try:
                exe = os.path.realpath(ancestor.exe())
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
                exe = f"<error: {type(exc).__name__}>"
            print(f"  pid={ancestor.pid} exe={exe}")
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
        print(f"  <ancestor walk failed: {type(exc).__name__}: {exc}>")

    yaml_path = Path.home() / ".claude" / "proj-session.yaml"
    print(f"proj-session.yaml slot for key '{resolved}':")
    if not yaml_path.exists():
        print("  <yaml file missing>")
        return
    try:
        import yaml as yaml_mod
        data = yaml_mod.safe_load(yaml_path.read_text())
    except (yaml_mod.YAMLError, OSError) as exc:
        print(f"  <read error: {exc}>")
        return
    if not isinstance(data, dict):
        print("  <yaml malformed>")
        return
    entries = data.get("active_by_claude_pid", {})
    if not isinstance(entries, dict):
        print("  <active_by_claude_pid malformed>")
        return
    slot = entries.get(resolved)
    if slot is None:
        print(f"  <missing — no entry for key '{resolved}' (yaml has keys: {list(entries.keys())})>")
        return
    print(f"  active: {slot.get('active', '<missing>')}")
    print(f"  last_seen: {slot.get('last_seen', '<missing>')}")
```

### Test

`plugins/proj/server/tests/test_cli.py` — add `TestDebugSessionKey` class with one test:

```python
class TestDebugSessionKey:
    def test_debug_session_key_prints_required_fields(self, tmp_path: Path) -> None:
        """Output must contain the 5 required fields. Don't assert exact pid values
        (depend on the test process); just structure.
        """
        result = _run_cli("debug-session-key")
        assert result.returncode == 0
        out = result.stdout
        assert "CLAUDE_CODE_EXECPATH:" in out
        assert "Resolved session key:" in out
        assert "Process: pid=" in out
        assert "Ancestor chain (immediate-first):" in out
        assert "proj-session.yaml slot for key '" in out
```

(Existing `_run_cli` helper from `test_cli.py` reused.)

## Version bump

`plugins/proj/.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`: `5.1.7` → `5.1.8`. Per-feature minor bump. README auto-regenerates via pre-commit hook.

This is the bump for the entire batch (777/778/783) — 783 rides along.

## Risks Accepted

- Test asserts only structure, not exact pid values. Real pids depend on the test process. Avoid flake.
- The pre-existing `test_cli.py` env quirk (worktree pytest may use pyenv python lacking `session_key`) is bypassed by running from the main repo's venv (consistent w/ prior batches).
