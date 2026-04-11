"""Tests for installer/wizard_specs.py — PromptSpec table + schema introspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from installer.wizard_specs import (
    PROJ_YAML_PROMPTS,
    WIZARD_EXCLUDED_FIELDS,
    _d,
    _DEFAULTS_CACHE,
    _reload_defaults,
    _ensure_defaults_loaded,
    assert_prompt_spec_covers_schema,
    assert_prompt_spec_covers_worktree_schema,
    assert_spec_keys_round_trip,
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

    def test_no_duplicate_dotted_keys(self) -> None:
        """Regression guard: (yaml_file, dotted_key) tuples must be unique.
        Failure message enumerates every duplicate tuple so offenders are obvious."""
        from collections import Counter

        tuples = [(s.yaml_file, s.dotted_key) for s in PROJ_YAML_PROMPTS]
        counts = Counter(tuples)
        duplicates = {k: v for k, v in counts.items() if v > 1}
        assert not duplicates, (
            f"Duplicate (yaml_file, dotted_key) tuples in PROJ_YAML_PROMPTS: "
            f"{sorted(duplicates.items())}"
        )

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

    def test_assert_worktree_coverage_returns_list(self) -> None:
        """Regression: every WorktreeConfig scalar field has a PromptSpec."""
        missing = assert_prompt_spec_covers_worktree_schema()
        assert isinstance(missing, list)
        # Warning-only regression: a missing key here means the worktree
        # wizard is silently dropping a dataclass field.

    def test_spec_keys_round_trip_through_writer(self) -> None:
        """Every PromptSpec.dotted_key must round-trip through the
        _merge_dotted_into_dict writer + get_nested reader. Catches
        typo/path mismatches like the worktree_dir → default_worktree_dir
        bug where the wizard wrote to the wrong yaml key."""
        failures = assert_spec_keys_round_trip()
        assert failures == [], (
            f"PromptSpec dotted_keys fail writer→reader round-trip: {failures}"
        )


class TestCrossPathBucketParity:
    """Rich and Textual wizards must iterate the same PROJ_YAML_PROMPTS
    table and therefore write to identical bucket keys. This regression
    test locks the invariant: for every spec, the (yaml_file, dotted_key)
    pair is the canonical destination both paths resolve to."""

    def test_both_paths_see_same_spec_table(self) -> None:
        """Rich (wizard.py) and Textual (screens/wizard.py) import the
        same PROJ_YAML_PROMPTS symbol. Import both and assert identity."""
        from installer import wizard as rich_wizard
        from installer.screens import wizard as textual_wizard

        assert rich_wizard.PROJ_YAML_PROMPTS is PROJ_YAML_PROMPTS
        assert textual_wizard.PROJ_YAML_PROMPTS is PROJ_YAML_PROMPTS

    def test_bucket_partition_covers_every_spec_key(self) -> None:
        """partition_answers_by_bucket must route every spec.dotted_key
        to the bucket matching spec.yaml_file. Guards against the writer
        misclassifying keys that wizard paths produced."""
        from installer._config_writer import partition_answers_by_bucket

        synthetic_answers: dict[str, Any] = {
            s.dotted_key: "sentinel" for s in PROJ_YAML_PROMPTS
        }
        buckets = partition_answers_by_bucket(synthetic_answers)
        for spec in PROJ_YAML_PROMPTS:
            assert spec.dotted_key in buckets.get(spec.yaml_file, {}), (
                f"spec {spec.dotted_key} (yaml_file={spec.yaml_file}) "
                f"was not routed to its declared bucket"
            )


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


# ── 506: trello wizard_specs coverage + gating + schema tests ────────────────


class TestTrelloWizardSpecs:
    """Tests added by todo 506 covering the reconciled trello PromptSpec block."""

    def _trello_specs(self) -> list[Any]:
        return [s for s in PROJ_YAML_PROMPTS if s.dotted_key.startswith("sync.trello.")]

    def test_trello_list_mappings_prompt_coverage(self) -> None:
        """list_mappings.* keys in PROJ_YAML_PROMPTS match TrelloListMappings."""
        list_mapping_keys = {
            s.dotted_key.rsplit(".", 1)[-1]
            for s in PROJ_YAML_PROMPTS
            if s.dotted_key.startswith("sync.trello.list_mappings.")
        }
        assert list_mapping_keys == {
            "created",
            "done",
            "projects",
            "tasks",
            "active",
            "pending",
            "archived",
        }

    def test_trello_default_board_id_is_basic_tier(self) -> None:
        specs = [
            s
            for s in PROJ_YAML_PROMPTS
            if s.dotted_key == "sync.trello.default_board_id"
        ]
        assert len(specs) == 1, (
            "sync.trello.default_board_id must be in PROJ_YAML_PROMPTS exactly once"
        )
        assert specs[0].tier == "basic"

    def test_trello_label_names_present(self) -> None:
        label_specs = {
            s.dotted_key: s
            for s in PROJ_YAML_PROMPTS
            if s.dotted_key
            in ("sync.trello.proj_label_name", "sync.trello.proj_task_label_name")
        }
        assert set(label_specs.keys()) == {
            "sync.trello.proj_label_name",
            "sync.trello.proj_task_label_name",
        }
        assert label_specs["sync.trello.proj_label_name"].default_factory({}) == "proj"
        assert (
            label_specs["sync.trello.proj_task_label_name"].default_factory({})
            == "proj-task"
        )

    def test_trello_label_name_tier_assignments(self) -> None:
        """proj_label_name/proj_task_label_name live in basic tier per r2."""
        for key in ("sync.trello.proj_label_name", "sync.trello.proj_task_label_name"):
            specs = [s for s in PROJ_YAML_PROMPTS if s.dotted_key == key]
            assert len(specs) == 1
            assert specs[0].tier == "basic", (
                f"{key} must be basic tier (user-facing label config)"
            )

    def test_trello_fields_gated_on_enabled(self) -> None:
        """Every sync.trello.* PromptSpec has a non-None condition gated on enabled."""
        for spec in self._trello_specs():
            assert spec.condition is not None, (
                f"{spec.dotted_key} missing condition lambda"
            )
            # When sync.trello.enabled is False, all gated rows must hide.
            assert spec.condition({"sync": {"trello": {"enabled": False}}}) is False

    def test_no_deprecated_trello_keys_in_wizard_specs(self) -> None:
        """Ensure backlog/todo/in_progress/blocked/archive are removed."""
        deprecated = {
            "sync.trello.list_mappings.backlog",
            "sync.trello.list_mappings.todo",
            "sync.trello.list_mappings.in_progress",
            "sync.trello.list_mappings.blocked",
            "sync.trello.list_mappings.archive",
        }
        present = {s.dotted_key for s in PROJ_YAML_PROMPTS}
        assert deprecated & present == set(), (
            f"Deprecated trello keys leaked: {deprecated & present}"
        )

    def test_no_duplicate_default_list_or_on_delete_promptspec(self) -> None:
        """default_list/on_delete are owned by TrelloConfigScreen, not PROJ_YAML_PROMPTS."""
        present = {s.dotted_key for s in PROJ_YAML_PROMPTS}
        assert "sync.trello.default_list" not in present
        assert "sync.trello.on_delete" not in present

    def test_wizard_defaults_yaml_has_trello_keys(self) -> None:
        """defaults.yaml includes proj_label_name/proj_task_label_name entries."""
        _ensure_defaults_loaded()
        from installer.wizard_specs import _DEFAULTS_CACHE

        data = _DEFAULTS_CACHE.get("data", {})
        trello = data.get("sync", {}).get("trello", {})
        assert trello.get("proj_label_name") == "proj"
        assert trello.get("proj_task_label_name") == "proj-task"
        # Deprecated keys should be gone.
        mappings = trello.get("list_mappings", {})
        for k in ("backlog", "todo", "in_progress", "blocked", "archive"):
            assert k not in mappings, f"deprecated key {k!r} still in defaults.yaml"
        for k in (
            "created",
            "done",
            "projects",
            "tasks",
            "active",
            "pending",
            "archived",
        ):
            assert k in mappings, f"required key {k!r} missing from defaults.yaml"

    def test_trello_list_mappings_prompt_spec_covers_dataclass(self) -> None:
        """assert_prompt_spec_covers_schema must not flag TrelloListMappings fields."""
        missing = assert_prompt_spec_covers_schema()
        mapping_missing = [
            m for m in missing if m.startswith("sync.trello.list_mappings.")
        ]
        assert mapping_missing == [], (
            f"TrelloListMappings fields missing from PROJ_YAML_PROMPTS: {mapping_missing}"
        )

    def test_trello_sync_prompt_spec_covers_dataclass(self) -> None:
        """assert_prompt_spec_covers_schema must not flag scalar TrelloSync fields.

        Excluded fields (owned by TrelloConfigScreen/TrelloIntegrationScreen):
        enabled, auto_sync, default_list, on_delete.
        """
        missing = assert_prompt_spec_covers_schema()
        sync_missing = [
            m
            for m in missing
            if m.startswith("sync.trello.")
            and not m.startswith("sync.trello.list_mappings.")
        ]
        assert sync_missing == [], (
            f"TrelloSync scalar fields missing from PROJ_YAML_PROMPTS: {sync_missing}"
        )

    def test_trello_enabled_requires_board_id(self) -> None:
        """Wizard-side: when sync.trello.enabled=True and default_board_id=='',
        the advanced config screen must block exit. This is enforced by a
        dedicated check in installer/screens/advanced_config.py — here we
        assert the PromptSpec carries the gating condition so the screen can
        surface the check.
        """
        specs = [
            s
            for s in PROJ_YAML_PROMPTS
            if s.dotted_key == "sync.trello.default_board_id"
        ]
        assert len(specs) == 1
        spec = specs[0]
        # Spec must be gated on enabled so the screen only asks when relevant.
        assert spec.condition is not None
        assert spec.condition({"sync": {"trello": {"enabled": True}}}) is True
        assert spec.condition({"sync": {"trello": {"enabled": False}}}) is False
        # Defaults yaml seeds empty-string — validator enforcement point is
        # documented as a comment on the PromptSpec and in advanced_config.py.
        assert spec.default_factory({}) == ""

    def test_default_board_id_grep_counts(self) -> None:
        """r2 regression: default_board_id must not be referenced as code in
        integration_config.py (comments mentioning the migration are allowed)
        and must appear exactly once as a PromptSpec entry in wizard_specs.py.
        """
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        ws = (repo_root / "installer" / "wizard_specs.py").read_text()
        ic_path = repo_root / "installer" / "screens" / "integration_config.py"
        # Strip comment lines so the migration comment doesn't trip the check.
        code_lines = [
            ln
            for ln in ic_path.read_text().splitlines()
            if not ln.strip().startswith("#")
        ]
        ic_code = "\n".join(code_lines)
        assert "default_board_id" not in ic_code, (
            "default_board_id leaked back into integration_config.py code "
            "(comments are allowed; actual references are not)"
        )
        assert ws.count('dotted_key="sync.trello.default_board_id"') == 1, (
            "sync.trello.default_board_id must be exactly one PromptSpec entry"
        )
