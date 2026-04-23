"""Category profile loader. 4 builtin profiles + custom support."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from server.lib.models import Profile

if TYPE_CHECKING:
    from pathlib import Path


class ProfileError(ValueError):
    """Raised for invalid or missing profile configuration."""


BUILTIN_PROFILES: dict[str, Profile] = {
    "software": Profile(
        name="software",
        categories=["concepts", "decisions", "references", "pitfalls", "entities"],
        session_section_map_default={
            "Key Decisions": "decisions",
            "Insights Discovered": "auto",
            "Related Todos": "links-only",
        },
    ),
    "personal": Profile(
        name="personal",
        categories=["journal", "topics", "people", "places", "lessons"],
        session_section_map_default={},
    ),
    "research": Profile(
        name="research",
        categories=["concepts", "sources", "findings", "questions"],
        session_section_map_default={},
    ),
    "minimal": Profile(
        name="minimal",
        categories=[],
        session_section_map_default={},
    ),
}


def get_builtin(name: str) -> Profile:
    """Get builtin profile by name; raise ProfileError if unknown."""
    if name not in BUILTIN_PROFILES:
        raise ProfileError(f"unknown builtin profile: {name!r}")
    return BUILTIN_PROFILES[name]


def load_profile(wiki_dir: Path) -> Profile:
    """Load active profile from wiki_dir/config.yaml.

    Supports builtin names (software/personal/research/minimal) + 'custom'.
    Builtin profiles may override `categories` via the config.
    """
    config_path = wiki_dir / "config.yaml"
    if not config_path.exists():
        raise ProfileError(f"config.yaml not found at {config_path}")

    try:
        with config_path.open() as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ProfileError(f"malformed config.yaml: {e}") from e

    profile_name = str(data.get("profile", "software"))
    categories_override = data.get("categories")

    if profile_name == "custom":
        if not categories_override:
            raise ProfileError("custom profile requires 'categories' list in config.yaml")
        return Profile(
            name="custom",
            categories=[str(c) for c in categories_override],
            session_section_map_default={},
        )

    if profile_name not in BUILTIN_PROFILES:
        raise ProfileError(f"unknown profile: {profile_name!r}")

    base = BUILTIN_PROFILES[profile_name]
    if categories_override is not None:
        return Profile(
            name=base.name,
            categories=[str(c) for c in categories_override],
            session_section_map_default=base.session_section_map_default,
        )
    return base


def save_profile(wiki_dir: Path, profile: Profile) -> None:
    """Persist the active profile choice to wiki_dir/config.yaml."""
    wiki_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "schema_version": 1,
        "profile": profile.name,
    }
    # For custom, always write categories. For builtins, write only if overridden.
    if profile.name == "custom":
        data["categories"] = list(profile.categories)
    else:
        base = BUILTIN_PROFILES[profile.name]
        if list(profile.categories) != list(base.categories):
            data["categories"] = list(profile.categories)

    with (wiki_dir / "config.yaml").open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
