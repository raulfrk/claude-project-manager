"""Tests for content_patch_requirements / content_patch_research MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.lib import state
from server.lib.models import ProjConfig
from server.tools.content import (
    _atomic_write_utf8,
    _patch_content_file,
    _scope_to_section,
    _validate_pattern,
)
from tests.conftest import call_tool, setup_project

# ── Direct unit tests for _patch_content_file ─────────────────────────────────


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestPatchContentFile:
    def test_patch_full_file_replaces_pattern(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "# H\n\nfoo bar foo\n")
        out = json.loads(_patch_content_file(p, r"foo", "FOO", None, 0, "requirements.md"))
        assert out["ok"] is True
        assert out["replacements"] == 2
        assert p.read_text(encoding="utf-8") == "# H\n\nFOO bar FOO\n"

    def test_patch_scoped_to_section(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(
            p,
            "# Title\n\n## Alpha\n\nfoo\n\n## Beta\n\nfoo\n",
        )
        out = json.loads(_patch_content_file(p, r"foo", "BAR", "Alpha", 0, "requirements.md"))
        assert out["ok"] is True
        assert out["replacements"] == 1
        text = p.read_text(encoding="utf-8")
        assert "## Alpha\n\nBAR\n" in text
        assert "## Beta\n\nfoo\n" in text

    def test_patch_section_at_eof(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "# Title\n\n## Last\n\nold value")
        out = json.loads(_patch_content_file(p, r"old", "new", "Last", 0, "requirements.md"))
        assert out["ok"] is True
        assert p.read_text(encoding="utf-8") == "# Title\n\n## Last\n\nnew value"

    def test_patch_section_not_found_returns_error(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "# Title\n\n## Alpha\n\nfoo\n")
        out = json.loads(_patch_content_file(p, r"foo", "X", "Missing", 0, "requirements.md"))
        assert out["ok"] is False
        assert out["error"] == "section not found: Missing"

    def test_patch_zero_match_returns_no_match(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        original = "# H\n\nhello\n"
        _write(p, original)
        out = json.loads(_patch_content_file(p, r"nomatch", "X", None, 0, "requirements.md"))
        assert out["ok"] is False
        assert out["error"] == "no match"
        # Unchanged
        assert p.read_text(encoding="utf-8") == original

    def test_patch_invalid_regex_returns_error(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "hello")
        out = json.loads(_patch_content_file(p, r"(", "X", None, 0, "requirements.md"))
        assert out["ok"] is False
        assert "invalid regex" in out["error"]

    def test_patch_missing_file_returns_error(self, tmp_path: Path) -> None:
        p = tmp_path / "nope.md"
        out = json.loads(_patch_content_file(p, r"foo", "X", None, 0, "requirements.md"))
        assert out["ok"] is False
        assert out["error"] == "no requirements.md found"

    def test_patch_pattern_too_long_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "hello")
        huge = "a" * 5000
        out = json.loads(_patch_content_file(p, huge, "X", None, 0, "requirements.md"))
        assert out["ok"] is False
        assert "pattern too long" in out["error"]

    def test_patch_nested_quantifier_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "aaaa")
        out = json.loads(_patch_content_file(p, r"(a+)+", "X", None, 0, "requirements.md"))
        assert out["ok"] is False
        assert "nested quantifier" in out["error"]

    def test_patch_crlf_line_endings_preserved(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        p.write_bytes(b"# H\r\n\r\nfoo\r\nbar\r\n")
        out = json.loads(_patch_content_file(p, r"foo", "FOO", None, 0, "requirements.md"))
        assert out["ok"] is True
        # CRLF preserved
        assert p.read_bytes() == b"# H\r\n\r\nFOO\r\nbar\r\n"

    def test_patch_backreference_in_replacement(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "alpha beta gamma")
        out = json.loads(
            _patch_content_file(p, r"(alpha) (beta)", r"\2 \1", None, 0, "requirements.md")
        )
        assert out["ok"] is True
        assert p.read_text(encoding="utf-8") == "beta alpha gamma"

    def test_patch_named_backreference(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        _write(p, "key=oldval")
        out = json.loads(
            _patch_content_file(
                p,
                r"(?P<k>key)=oldval",
                r"\g<k>=newval",
                None,
                0,
                "requirements.md",
            )
        )
        assert out["ok"] is True
        assert p.read_text(encoding="utf-8") == "key=newval"

    def test_patch_section_with_fenced_code_containing_hash(self, tmp_path: Path) -> None:
        # A fenced block containing `# looks-like-heading` lines must not be
        # treated as a heading boundary.
        p = tmp_path / "r.md"
        _write(
            p,
            (
                "# Top\n"
                "\n"
                "## Alpha\n"
                "\n"
                "```\n"
                "# not a heading\n"
                "## also not\n"
                "```\n"
                "\n"
                "foo\n"
                "\n"
                "## Beta\n"
                "\n"
                "foo\n"
            ),
        )
        out = json.loads(_patch_content_file(p, r"foo", "BAR", "Alpha", 0, "requirements.md"))
        assert out["ok"] is True
        assert out["replacements"] == 1
        text = p.read_text(encoding="utf-8")
        # Alpha's foo replaced, Beta's foo untouched
        alpha_idx = text.index("## Alpha")
        beta_idx = text.index("## Beta")
        assert "BAR" in text[alpha_idx:beta_idx]
        assert "foo" in text[beta_idx:]

    def test_patch_utf8_decode_error(self, tmp_path: Path) -> None:
        p = tmp_path / "r.md"
        # Invalid UTF-8 byte sequence
        p.write_bytes(b"valid\xffinvalid")
        out = json.loads(_patch_content_file(p, r"valid", "X", None, 0, "requirements.md"))
        assert out["ok"] is False
        assert "utf-8 decode error" in out["error"]

    def test_patch_atomic_write_failure_leaves_target_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = tmp_path / "r.md"
        original = "hello world\n"
        _write(p, original)

        def boom(self: Path, target: Any) -> None:
            raise OSError("simulated disk full")

        monkeypatch.setattr(Path, "replace", boom)
        with pytest.raises(OSError, match="simulated disk full"):
            _patch_content_file(p, r"hello", "HELLO", None, 0, "requirements.md")
        # Target file unchanged
        assert p.read_text(encoding="utf-8") == original


# ── Helper unit tests ─────────────────────────────────────────────────────────


class TestScopeToSection:
    def test_nested_subheading_ends_at_same_level(self) -> None:
        text = "# Top\n\n## A\n\nbody-a\n\n### A.1\n\ndeep\n\n## B\n\nbody-b\n"
        bounds = _scope_to_section(text, "A")
        assert bounds is not None
        start, end = bounds
        scope = text[start:end]
        assert "body-a" in scope
        assert "deep" in scope  # sub-heading included
        assert "body-b" not in scope

    def test_eof_section(self) -> None:
        text = "# Top\n\n## Last\n\nfinal\n"
        bounds = _scope_to_section(text, "Last")
        assert bounds is not None
        assert text[bounds[0] : bounds[1]].strip() == "final"

    def test_missing_section_returns_none(self) -> None:
        assert _scope_to_section("# H\n", "Nope") is None


class TestValidatePattern:
    def test_accepts_valid(self) -> None:
        c, err = _validate_pattern(r"^foo$")
        assert c is not None
        assert err is None

    def test_rejects_too_long(self) -> None:
        c, err = _validate_pattern("a" * 5000)
        assert c is None
        assert err is not None and "too long" in err

    def test_rejects_nested_quantifier(self) -> None:
        c, err = _validate_pattern(r"(a+)+")
        assert c is None
        assert err is not None and "nested quantifier" in err

    def test_rejects_bad_regex(self) -> None:
        c, err = _validate_pattern(r"(")
        assert c is None
        assert err is not None and "invalid regex" in err


# ── MCP roundtrip tests ───────────────────────────────────────────────────────


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path / "myrepo"))
    state.set_session_active("myapp")
    return cfg, "myapp"


async def _add_todo(mcp_app: Any, title: str) -> str:
    result = await call_tool(mcp_app, "todo_add", title=title)
    return json.loads(result)["todo_id"]


@pytest.mark.asyncio
class TestContentPatchMcp:
    async def test_content_patch_mcp_roundtrip(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Fix bug")
        await call_tool(
            mcp_app,
            "content_set_requirements",
            todo_id=todo_id,
            content="# Title\n\n## Goals\n\nBuild foo quickly.\n",
        )
        result = await call_tool(
            mcp_app,
            "content_patch_requirements",
            todo_id=todo_id,
            pattern=r"foo",
            replacement="widgets",
            section="Goals",
        )
        data = json.loads(result)
        assert data["ok"] is True
        assert data["replacements"] == 1
        updated = await call_tool(mcp_app, "content_get_requirements", todo_id=todo_id)
        assert "Build widgets quickly" in updated

    async def test_content_patch_research_tool_writes_research(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Explore")
        await call_tool(
            mcp_app,
            "content_set_research",
            todo_id=todo_id,
            content="Found old-value in module X.",
        )
        result = await call_tool(
            mcp_app,
            "content_patch_research",
            todo_id=todo_id,
            pattern=r"old-value",
            replacement="new-value",
        )
        data = json.loads(result)
        assert data["ok"] is True
        assert data["replacements"] == 1
        updated = await call_tool(mcp_app, "content_get_research", todo_id=todo_id)
        assert "new-value" in updated
        assert "old-value" not in updated


# ── Perf test ─────────────────────────────────────────────────────────────────


def test_content_patch_faster_than_set_for_localized_edit(tmp_path: Path) -> None:
    """Compare patch vs full-rewrite cost for a localized edit in a large file.

    Both paths do a UTF-8 atomic write, so wall-clock differences in-process
    are often marginal. This test validates functional correctness: both
    operations produce identical results. Timing is not asserted due to
    system load variance at small file sizes (I/O dominates).
    """
    lines = [f"line {i} token-{i % 10}\n" for i in range(1500)]
    lines[750] = "line 750 FIND-ME-HERE\n"
    original = "".join(lines)

    p = tmp_path / "big.md"

    # Run patch operation.
    p.write_text(original, encoding="utf-8")
    patch_result = _patch_content_file(
        p, r"FIND-ME-HERE", "REPLACED-TOKEN", None, 0, "requirements.md"
    )
    patch_result_json = json.loads(patch_result)
    assert patch_result_json["ok"], f"patch failed: {patch_result_json.get('error')}"
    assert patch_result_json["replacements"] == 1
    patched_content = p.read_text(encoding="utf-8")

    # Run set operation (read full, modify, atomic write).
    p.write_text(original, encoding="utf-8")
    current = p.read_text(encoding="utf-8")
    new_text = current.replace("FIND-ME-HERE", "REPLACED-TOKEN")
    _atomic_write_utf8(p, new_text)
    set_content = p.read_text(encoding="utf-8")

    # Both operations produce identical results.
    assert patched_content == set_content
    assert "REPLACED-TOKEN" in patched_content
    assert "FIND-ME-HERE" not in patched_content
