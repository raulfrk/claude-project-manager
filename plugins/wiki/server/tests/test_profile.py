"""Tests for lib/profile.py."""

from pathlib import Path

import pytest
import yaml

from server.lib.models import Profile
from server.lib.profile import (
    BUILTIN_PROFILES,
    ProfileError,
    get_builtin,
    load_profile,
    save_profile,
)


class TestBuiltinProfiles:
    def test_all_four_present(self) -> None:
        assert set(BUILTIN_PROFILES.keys()) == {"software", "personal", "research", "minimal"}

    def test_software_shape(self) -> None:
        p = get_builtin("software")
        assert p.name == "software"
        assert "decisions" in p.categories
        assert "concepts" in p.categories
        assert "references" in p.categories
        assert "pitfalls" in p.categories
        assert "entities" in p.categories
        assert len(p.categories) == 5

    def test_personal_shape(self) -> None:
        p = get_builtin("personal")
        assert "journal" in p.categories
        assert "topics" in p.categories
        assert "people" in p.categories
        assert "places" in p.categories
        assert "lessons" in p.categories

    def test_research_shape(self) -> None:
        p = get_builtin("research")
        assert set(p.categories) == {"concepts", "sources", "findings", "questions"}

    def test_minimal_is_empty(self) -> None:
        p = get_builtin("minimal")
        assert p.categories == []

    def test_unknown_raises(self) -> None:
        with pytest.raises(ProfileError, match="unknown builtin"):
            get_builtin("nonexistent")


class TestLoadProfile:
    def test_load_builtin_by_name(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "profile": "software",
                }
            )
        )
        p = load_profile(wiki_root)
        assert p.name == "software"
        assert "decisions" in p.categories

    def test_load_custom_categories_override(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "profile": "custom",
                    "categories": ["foo", "bar", "baz"],
                }
            )
        )
        p = load_profile(wiki_root)
        assert p.name == "custom"
        assert p.categories == ["foo", "bar", "baz"]

    def test_load_builtin_with_category_override(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "profile": "software",
                    "categories": ["concepts", "decisions"],  # override
                }
            )
        )
        p = load_profile(wiki_root)
        assert p.name == "software"
        assert p.categories == ["concepts", "decisions"]

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileError, match=r"config\.yaml not found"):
            load_profile(tmp_path)

    def test_custom_without_categories_raises(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "profile": "custom",
                }
            )
        )
        with pytest.raises(ProfileError, match="custom profile requires"):
            load_profile(wiki_root)

    def test_unknown_builtin_raises(self, wiki_root: Path) -> None:
        (wiki_root / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "profile": "not-a-real-profile",
                }
            )
        )
        with pytest.raises(ProfileError, match="unknown"):
            load_profile(wiki_root)


class TestSaveProfile:
    def test_save_builtin(self, wiki_root: Path) -> None:
        p = get_builtin("software")
        save_profile(wiki_root, p)
        assert (wiki_root / "config.yaml").exists()
        data = yaml.safe_load((wiki_root / "config.yaml").read_text())
        assert data["profile"] == "software"

    def test_save_custom_writes_categories(self, wiki_root: Path) -> None:
        p = Profile(
            name="custom",
            categories=["a", "b"],
            session_section_map_default={},
        )
        save_profile(wiki_root, p)
        data = yaml.safe_load((wiki_root / "config.yaml").read_text())
        assert data["profile"] == "custom"
        assert data["categories"] == ["a", "b"]

    def test_save_roundtrip(self, wiki_root: Path) -> None:
        p = get_builtin("personal")
        save_profile(wiki_root, p)
        loaded = load_profile(wiki_root)
        assert loaded.name == p.name
        assert loaded.categories == p.categories


class TestProfileMalformedYaml:
    def test_malformed_config_raises_profile_error(self, tmp_path: Path) -> None:
        wiki_dir = tmp_path
        (wiki_dir / "config.yaml").write_text("profile: [unclosed-bracket\n")

        with pytest.raises(ProfileError, match="malformed"):
            load_profile(wiki_dir)
