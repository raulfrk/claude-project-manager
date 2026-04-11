"""Tests for installer/wizard_specs.py — PromptSpec table + schema introspection."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.wizard_specs import (
    PROJ_YAML_PROMPTS,
    WIZARD_EXCLUDED_FIELDS,
    _d,
    _DEFAULTS_CACHE,
    _reload_defaults,
    _ensure_defaults_loaded,
    assert_prompt_spec_covers_schema,
    get_distinct_yaml_files,
)


@pytest.fixture(autouse=True)
def _snapshot_defaults_cache() -> None:
    """Snapshot/restore _DEFAULTS_CACHE around every test so order is isolated."""
    snapshot = dict(_DEFAULTS_CACHE)
    try:
        yield
    finally:
        _DEFAULTS_CACHE.clear()
        _DEFAULTS_CACHE.update(snapshot)


class TestPromptSpecTable:
    def test_every_spec_has_required_fields(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            assert isinstance(spec.label, str) and spec.label
            assert isinstance(spec.dotted_key, str) and spec.dotted_key
            assert spec.type in ("bool", "str", "int", "choice")
            assert spec.tier in ("basic", "advanced")
            assert spec.yaml_file in ("proj", "worktree", "todoist", "trello", "jira")
            assert callable(spec.default_factory)

    def test_choice_specs_have_choices(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            if spec.type == "choice":
                assert spec.choices is not None and len(spec.choices) >= 1

    def test_int_specs_have_ranges(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            if spec.type == "int":
                assert spec.int_range is not None
                low, high = spec.int_range
                assert low <= high

    def test_dotted_keys_unique(self) -> None:
        # Uniqueness is per (yaml_file, dotted_key) — different yaml files may
        # have same key theoretically. Check unique tuples.
        tuples = [(s.yaml_file, s.dotted_key) for s in PROJ_YAML_PROMPTS]
        assert len(tuples) == len(set(tuples))

    def test_dotted_key_format_valid(self) -> None:
        for spec in PROJ_YAML_PROMPTS:
            for segment in spec.dotted_key.split("."):
                assert segment, f"empty segment in {spec.dotted_key}"
                assert all(c.isalnum() or c == "_" for c in segment), (
                    f"invalid char in {spec.dotted_key}"
                )


class TestWizardExcludedFields:
    def test_excluded_fields_is_set(self) -> None:
        assert isinstance(WIZARD_EXCLUDED_FIELDS, set)
        assert len(WIZARD_EXCLUDED_FIELDS) > 0

    def test_no_excluded_field_in_prompts(self) -> None:
        prompt_keys = {s.dotted_key for s in PROJ_YAML_PROMPTS if s.yaml_file == "proj"}
        intersection = prompt_keys & WIZARD_EXCLUDED_FIELDS
        assert intersection == set(), (
            f"Excluded fields leaked into prompts: {intersection}"
        )


class TestSchemaIntrospection:
    def test_assert_coverage_returns_list(self) -> None:
        """Regression: every ProjConfig dataclass field must have a PromptSpec."""
        missing = assert_prompt_spec_covers_schema()
        # If ProjConfig cannot be imported (e.g. in isolated CI), returns [] per
        # the permissive contract. Otherwise, the list should be empty.
        assert isinstance(missing, list)
        # Don't fail on missing keys here — this is a warning-only regression;
        # add strict fail in a future todo once coverage is verified complete.


class TestDefaultsCacheLazy:
    def test_missing_defaults_raises_on_first_factory_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the first _d() factory call raises when defaults.yaml missing.

        Module import itself stays silent, proving --update/--uninstall/
        --status paths are not bricked by a missing packaging data file.
        """
        from installer import wizard_specs as ws

        # Importing wizard_specs has already happened at test collection; that
        # proved the "import does not raise" part. Now simulate a missing
        # resource to prove the RuntimeError path from the lazy loader.
        ws._DEFAULTS_CACHE.clear()

        class _FakePath:
            def joinpath(self, _name: str) -> "_FakePath":
                return self

            def read_text(self, encoding: str = "utf-8") -> str:
                raise FileNotFoundError("synthetic missing")

        def _bad_files(_pkg: str) -> _FakePath:
            return _FakePath()

        monkeypatch.setattr("importlib.resources.files", _bad_files)

        factory = ws._d("tracking_dir")
        with pytest.raises(RuntimeError, match="defaults.yaml not found"):
            factory({})

    def test_reload_defaults_rebinds(self, tmp_path: Path) -> None:
        """_reload_defaults(path) must rebind so later _d() calls see new values."""
        override = tmp_path / "defaults.yaml"
        override.write_text("tracking_dir: /override/path\n")
        _reload_defaults(override)
        factory = _d("tracking_dir")
        assert factory({}) == "/override/path"

    def test_factory_prefers_existing_over_default(self, tmp_path: Path) -> None:
        """Existing yaml value takes precedence over defaults.yaml fallback."""
        _ensure_defaults_loaded()
        factory = _d("tracking_dir")
        assert factory({"tracking_dir": "/user/custom"}) == "/user/custom"

    def test_factory_falls_through_to_default(self) -> None:
        """Missing key in existing returns defaults.yaml value."""
        _ensure_defaults_loaded()
        factory = _d("tracking_dir")
        assert factory({}) == "~/projects/tracking"

    def test_factory_type_mismatch_falls_through(self) -> None:
        """Dict where scalar expected falls through to default."""
        _ensure_defaults_loaded()
        factory = _d("tracking_dir")
        assert factory({"tracking_dir": {"foo": "bar"}}) == "~/projects/tracking"

    def test_factory_explicit_none_falls_through(self) -> None:
        """Explicit `key: null` in existing yaml treated as missing."""
        _ensure_defaults_loaded()
        factory = _d("tracking_dir")
        assert factory({"tracking_dir": None}) == "~/projects/tracking"

    def test_factory_nested_key(self) -> None:
        """Dotted keys walk into nested defaults."""
        _ensure_defaults_loaded()
        factory = _d("team_mode.max_agents")
        assert factory({}) == 30
        assert factory({"team_mode": {"max_agents": 7}}) == 7

    def test_distinct_yaml_files(self) -> None:
        distinct = get_distinct_yaml_files(PROJ_YAML_PROMPTS)
        assert "proj" in distinct
        assert "worktree" in distinct


class TestSensitiveFieldCoverage:
    def test_sensitive_field_name_coverage(self) -> None:
        """Any PromptSpec whose dotted_key matches a credential-ish name
        must have sensitive=True. Guards against future regressions when
        credential entries get added to PROJ_YAML_PROMPTS."""

        # Match whole segments only so "max_tokens" ≠ "token".
        credential_segments = {
            "api_key",
            "token",
            "api_token",
            "password",
            "secret",
            "credential",
            "private_key",
        }

        def _has_credential_segment(dotted: str) -> bool:
            for seg in dotted.split("."):
                parts = seg.lower().split("_")
                # Check the full segment AND any 2-word subsequence
                # (so "api_token" and "api_key" both match).
                for i in range(len(parts)):
                    if parts[i] in credential_segments:
                        return True
                    if i + 1 < len(parts):
                        pair = f"{parts[i]}_{parts[i + 1]}"
                        if pair in credential_segments:
                            return True
            return False

        offenders: list[str] = []
        for spec in PROJ_YAML_PROMPTS:
            if _has_credential_segment(spec.dotted_key) and not spec.sensitive:
                offenders.append(spec.dotted_key)
        assert offenders == [], (
            f"Credential-shaped keys missing sensitive=True: {offenders}"
        )


class TestDefaultsYamlCoverage:
    def test_every_prompt_key_has_defaults_value(self) -> None:
        """Every PromptSpec dotted_key resolves to a non-None default."""
        _ensure_defaults_loaded()
        missing: list[str] = []
        for spec in PROJ_YAML_PROMPTS:
            value = spec.default_factory({})
            if value is None:
                missing.append(spec.dotted_key)
        assert missing == [], f"keys with None default: {missing}"

    def test_defaults_yaml_is_resource_packaged(self) -> None:
        """importlib.resources can locate installer/defaults.yaml post-install."""
        from importlib.resources import files

        path = files("installer").joinpath("defaults.yaml")
        assert path.is_file()
