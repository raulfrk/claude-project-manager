"""Tests for installer/_config_loader.py — shared yaml loader + nested dict walker."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from installer._config_loader import ConfigLoadError, get_nested, load_existing_yaml


class TestLoadExistingYaml:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_existing_yaml(tmp_path / "missing.yaml") == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.yaml"
        p.write_text("")
        assert load_existing_yaml(p) == {}

    def test_whitespace_only_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "whitespace.yaml"
        p.write_text("   \n\n  ")
        assert load_existing_yaml(p) == {}

    def test_valid_yaml_returns_dict(self, tmp_path: Path) -> None:
        p = tmp_path / "valid.yaml"
        p.write_text("foo: bar\nbaz: 42\n")
        assert load_existing_yaml(p) == {"foo": "bar", "baz": 42}

    def test_null_document_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "null.yaml"
        p.write_text("null\n")
        assert load_existing_yaml(p) == {}

    def test_list_top_level_returns_empty(self, tmp_path: Path) -> None:
        """Non-dict top-level values are treated as empty."""
        p = tmp_path / "list.yaml"
        p.write_text("- a\n- b\n")
        assert load_existing_yaml(p) == {}

    def test_invalid_yaml_raises_config_load_error(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("foo: bar\n  baz: 42\n invalid: - - -\n}}")
        with pytest.raises(ConfigLoadError) as excinfo:
            load_existing_yaml(p)
        assert excinfo.value.path == p
        assert excinfo.value.original is not None

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason="chmod 000 test requires POSIX and non-root",
    )
    def test_permission_denied_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "locked.yaml"
        p.write_text("foo: bar\n")
        p.chmod(0o000)
        try:
            with pytest.raises(ConfigLoadError):
                load_existing_yaml(p)
        finally:
            p.chmod(0o600)

    def test_size_ceiling_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "huge.yaml"
        # 1 MB + 1 byte of valid yaml filler
        p.write_bytes(b"key: " + b"a" * (1_048_576 + 1) + b"\n")
        with pytest.raises(ConfigLoadError, match="too large"):
            load_existing_yaml(p)

    def test_size_at_ceiling_loads(self, tmp_path: Path) -> None:
        p = tmp_path / "exact.yaml"
        # Construct a yaml file whose size is exactly 1 MB
        content = b"key: " + b"a" * (1_048_576 - len(b"key: \n")) + b"\n"
        assert len(content) == 1_048_576
        p.write_bytes(content)
        data = load_existing_yaml(p)
        assert isinstance(data, dict)

    def test_utf8_bom_tolerated(self, tmp_path: Path) -> None:
        p = tmp_path / "bom.yaml"
        p.write_bytes("\ufeff".encode("utf-8") + b"foo: bar\n")
        assert load_existing_yaml(p) == {"foo": "bar"}

    def test_directory_rejected(self, tmp_path: Path) -> None:
        d = tmp_path / "subdir"
        d.mkdir()
        with pytest.raises(ConfigLoadError, match="not a regular file"):
            load_existing_yaml(d)

    def test_symlink_escaping_claude_home_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pretend home is at tmp_path/home so ~/.claude is under it.
        fake_home = tmp_path / "home"
        fake_claude = fake_home / ".claude"
        fake_claude.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        target = tmp_path / "outside.yaml"
        target.write_text("foo: bar\n")
        link = fake_claude / "proj.yaml"
        link.symlink_to(target)
        with pytest.raises(ConfigLoadError, match="escapes"):
            load_existing_yaml(link)

    def test_symlink_inside_claude_home_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        fake_claude = fake_home / ".claude"
        fake_claude.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        target = fake_claude / "real.yaml"
        target.write_text("foo: bar\n")
        link = fake_claude / "proj.yaml"
        link.symlink_to(target)
        assert load_existing_yaml(link) == {"foo": "bar"}

    def test_explicit_null_value_treated_as_missing(self, tmp_path: Path) -> None:
        """Explicit `key: null` still loads; get_nested handles the null."""
        p = tmp_path / "nulled.yaml"
        p.write_text("api_token: null\n")
        data = load_existing_yaml(p)
        assert data == {"api_token": None}
        # get_nested contract: explicit null → default
        assert get_nested(data, "api_token", "default") == "default"


class TestGetNested:
    def test_simple_lookup(self) -> None:
        assert get_nested({"a": 1}, "a") == 1

    def test_nested_lookup(self) -> None:
        d = {"a": {"b": {"c": 42}}}
        assert get_nested(d, "a.b.c") == 42

    def test_missing_key_returns_default(self) -> None:
        assert get_nested({"a": 1}, "b", "default") == "default"

    def test_missing_nested_returns_default(self) -> None:
        d = {"a": {"b": 1}}
        assert get_nested(d, "a.c.d", "fallback") == "fallback"

    def test_intermediate_none_returns_default(self) -> None:
        d = {"a": {"b": None}}
        assert get_nested(d, "a.b.c", "fallback") == "fallback"

    def test_intermediate_non_dict_returns_default(self) -> None:
        d = {"a": 42}
        assert get_nested(d, "a.b", "fallback") == "fallback"

    def test_final_none_returns_default(self) -> None:
        d = {"a": {"b": None}}
        assert get_nested(d, "a.b", "fallback") == "fallback"

    def test_empty_key_returns_default(self) -> None:
        assert get_nested({"a": 1}, "", "fallback") == "fallback"

    def test_no_default_returns_none(self) -> None:
        assert get_nested({}, "a.b") is None
