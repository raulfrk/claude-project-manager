"""Unit tests for scripts/check_deps.py.

Dependency conflict detection and superset validation.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "check_deps",
    Path(__file__).resolve().parent.parent / "scripts" / "check_deps.py",
)
assert _spec and _spec.loader
check_deps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_deps)  # type: ignore[union-attr]

# Re-export for convenience
normalize = check_deps.normalize
parse_deps = check_deps.parse_deps
check_conflicts = check_deps.check_conflicts
validate_superset = check_deps.validate_superset
find_plugin_pyprojects = check_deps.find_plugin_pyprojects
parse_root_plugin_deps = check_deps.parse_root_plugin_deps
main = check_deps.main


# ── normalize ───────────────────────────────────────────────────────


class TestNormalize:
    def test_lowercase(self) -> None:
        assert normalize("PyYAML") == "pyyaml"

    def test_dash_collapse(self) -> None:
        assert normalize("my_cool-package") == "my-cool-package"

    def test_dots(self) -> None:
        assert normalize("a.b..c") == "a-b-c"

    def test_already_normalized(self) -> None:
        assert normalize("simple") == "simple"

    def test_mixed(self) -> None:
        assert normalize("My__Package.Name") == "my-package-name"


# ── parse_deps ──────────────────────────────────────────────────────


class TestParseDeps:
    def test_basic(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            textwrap.dedent("""\
            [project]
            name = "test"
            version = "0.1.0"
            dependencies = ["httpx>=0.28", "pyyaml>=6.0"]
            """)
        )
        reqs = parse_deps(toml)
        names = sorted(r.name for r in reqs)
        assert names == ["httpx", "pyyaml"]

    def test_empty_deps(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            textwrap.dedent("""\
            [project]
            name = "test"
            version = "0.1.0"
            dependencies = []
            """)
        )
        assert parse_deps(toml) == []

    def test_no_deps_key(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            textwrap.dedent("""\
            [project]
            name = "test"
            version = "0.1.0"
            """)
        )
        assert parse_deps(toml) == []

    def test_preserves_specifiers(self, tmp_path: Path) -> None:
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            textwrap.dedent("""\
            [project]
            name = "test"
            version = "0.1.0"
            dependencies = ["mcp>=1.2.0,<2"]
            """)
        )
        reqs = parse_deps(toml)
        assert len(reqs) == 1
        # packaging may reorder specifiers; check both parts are present
        spec_str = str(reqs[0].specifier)
        assert ">=1.2.0" in spec_str
        assert "<2" in spec_str


# ── check_conflicts ────────────────────────────────────────────────


class TestCheckConflicts:
    def _make_req(self, s: str):
        from packaging.requirements import Requirement

        return Requirement(s)

    def test_no_conflict_same_specifier(self) -> None:
        plugin_deps = {
            "proj": [self._make_req("httpx>=0.28")],
            "hooks": [self._make_req("httpx>=0.28")],
        }
        assert check_conflicts(plugin_deps) == []

    def test_no_conflict_compatible_specifiers(self) -> None:
        plugin_deps = {
            "proj": [self._make_req("httpx>=0.28")],
            "hooks": [self._make_req("httpx>=0.25")],
        }
        assert check_conflicts(plugin_deps) == []

    def test_no_conflict_one_any(self) -> None:
        """One plugin pins, the other has no specifier -- no conflict."""
        plugin_deps = {
            "proj": [self._make_req("httpx>=0.28")],
            "hooks": [self._make_req("httpx")],
        }
        assert check_conflicts(plugin_deps) == []

    def test_conflict_detected(self) -> None:
        """Mutually exclusive ranges should be flagged."""
        plugin_deps = {
            "alpha": [self._make_req("httpx>=100.0")],
            "beta": [self._make_req("httpx<1.0")],
        }
        errors = check_conflicts(plugin_deps)
        assert len(errors) == 1
        assert "CONFLICT" in errors[0]
        assert "httpx" in errors[0]

    def test_single_plugin_no_conflict(self) -> None:
        plugin_deps = {
            "proj": [self._make_req("httpx>=0.28"), self._make_req("pyyaml>=6.0")],
        }
        assert check_conflicts(plugin_deps) == []

    def test_multiple_conflicts(self) -> None:
        plugin_deps = {
            "a": [self._make_req("foo>=100"), self._make_req("bar<1")],
            "b": [self._make_req("foo<1"), self._make_req("bar>=100")],
        }
        errors = check_conflicts(plugin_deps)
        assert len(errors) == 2

    def test_normalized_names_grouped(self) -> None:
        """httpx and HTTPX should be grouped together (no conflict here)."""
        plugin_deps = {
            "proj": [self._make_req("httpx>=0.28")],
            "hooks": [self._make_req("HTTPX>=0.25")],
        }
        assert check_conflicts(plugin_deps) == []


# ── validate_superset ──────────────────────────────────────────────


class TestValidateSuperset:
    def _make_req(self, s: str):
        from packaging.requirements import Requirement

        return Requirement(s)

    def test_all_covered(self) -> None:
        root = [self._make_req("httpx>=0.28"), self._make_req("pyyaml>=6.0")]
        plugin_deps = {
            "proj": [self._make_req("httpx>=0.28")],
            "hooks": [self._make_req("pyyaml>=6.0")],
        }
        with patch.object(check_deps, "_find_local_source_names", return_value=set()):
            errors = validate_superset(root, plugin_deps)
        assert errors == []

    def test_missing_dep(self) -> None:
        root = [self._make_req("httpx>=0.28")]
        plugin_deps = {
            "proj": [self._make_req("httpx>=0.28"), self._make_req("pyyaml>=6.0")],
        }
        with patch.object(check_deps, "_find_local_source_names", return_value=set()):
            errors = validate_superset(root, plugin_deps)
        assert len(errors) == 1
        assert "pyyaml" in errors[0]
        assert "MISSING" in errors[0]

    def test_local_deps_excluded(self) -> None:
        """Deps listed in [tool.uv.sources] (local path deps) should not be flagged."""
        root: list = []
        plugin_deps = {
            "hooks": [self._make_req("claude-hook-transport>=0.1")],
        }
        with patch.object(
            check_deps,
            "_find_local_source_names",
            return_value={"claude-hook-transport"},
        ):
            errors = validate_superset(root, plugin_deps)
        assert errors == []

    def test_multiple_plugins_missing_same(self) -> None:
        root: list = []
        plugin_deps = {
            "proj": [self._make_req("missing-pkg>=1.0")],
            "hooks": [self._make_req("missing-pkg>=2.0")],
        }
        with patch.object(check_deps, "_find_local_source_names", return_value=set()):
            errors = validate_superset(root, plugin_deps)
        assert len(errors) == 1
        assert "hooks" in errors[0]
        assert "proj" in errors[0]


# ── main (integration-ish) ──────────────────────────────────────────


class TestMain:
    def test_clean_returns_zero(self) -> None:
        """With no conflicts and full coverage, main() should return 0."""
        with (
            patch.object(check_deps, "find_plugin_deps", return_value={}),
            patch.object(check_deps, "parse_root_plugin_deps", return_value=[]),
        ):
            assert main() == 0

    def test_conflict_returns_one(self) -> None:
        from packaging.requirements import Requirement

        deps = {
            "a": [Requirement("foo>=100")],
            "b": [Requirement("foo<1")],
        }
        root = [Requirement("foo>=1")]
        with (
            patch.object(check_deps, "find_plugin_deps", return_value=deps),
            patch.object(check_deps, "parse_root_plugin_deps", return_value=root),
        ):
            assert main() == 1

    def test_missing_returns_one(self) -> None:
        from packaging.requirements import Requirement

        deps = {"a": [Requirement("novelpackage>=1.0")]}
        root: list = []
        with (
            patch.object(check_deps, "find_plugin_deps", return_value=deps),
            patch.object(check_deps, "parse_root_plugin_deps", return_value=root),
            patch.object(check_deps, "_find_local_source_names", return_value=set()),
        ):
            assert main() == 1


# ── find_plugin_pyprojects (against real repo) ─────────────────────


@pytest.mark.integration
class TestFindPluginPyprojects:
    def test_finds_real_plugins(self) -> None:
        """Sanity check: should find at least the known plugins."""
        paths = find_plugin_pyprojects()
        labels = [p.relative_to(check_deps.ROOT / "plugins").parts[0] for p in paths]
        # At minimum, proj and hooks should exist
        assert "proj" in labels
        assert "hooks" in labels

    def test_includes_shared(self) -> None:
        paths = find_plugin_pyprojects()
        labels = [p.relative_to(check_deps.ROOT / "plugins").parts[0] for p in paths]
        assert "_shared" in labels
