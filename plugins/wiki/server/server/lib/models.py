"""Typed dataclasses for wiki config, profiles, + pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


@dataclass
class WikiConfig:
    """Runtime configuration from ~/.claude/wiki.yaml."""

    enabled: bool = False
    wiki_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "wiki")
    reingest_cooldown_hours: int = 24
    bootstrap_pending: bool = False
    session_ingest_section_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WikiConfig:
        wiki_dir_raw = data.get("wiki_dir")
        wiki_dir = (
            Path(str(wiki_dir_raw)).expanduser()
            if wiki_dir_raw
            else Path.home() / ".claude" / "wiki"
        )
        session_ingest = data.get("session_ingest", {}) or {}  # type: ignore[assignment]
        if isinstance(session_ingest, dict):
            section_map = cast("dict[str, str]", session_ingest.get("section_map", {}))  # type: ignore[arg-type]
        else:
            section_map = {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            wiki_dir=wiki_dir,
            reingest_cooldown_hours=int(data.get("reingest_cooldown_hours", 24)),
            bootstrap_pending=bool(data.get("bootstrap_pending", False)),
            session_ingest_section_map=section_map,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "wiki_dir": str(self.wiki_dir),
            "reingest_cooldown_hours": self.reingest_cooldown_hours,
            "bootstrap_pending": self.bootstrap_pending,
            "session_ingest": {"section_map": dict(self.session_ingest_section_map)},
        }


@dataclass
class Profile:
    """Category profile loaded from ~/.claude/wiki/config.yaml."""

    name: str
    categories: list[str]
    session_section_map_default: dict[str, str]

    def __post_init__(self) -> None:
        if self.name != "minimal" and not self.categories:
            raise ValueError("Profile categories cannot be empty (except for 'minimal' profile)")


@dataclass
class Page:
    """A wiki page: filesystem path + parsed frontmatter + body text."""

    path: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", ""))

    @property
    def slug(self) -> str:
        return self.path.stem

    @property
    def tags(self) -> list[str]:
        raw = self.frontmatter.get("tags", []) or []  # type: ignore[assignment]
        if isinstance(raw, list):
            return [str(t) for t in cast("list[Any]", raw)]
        return []

    @property
    def scope(self) -> list[str]:
        raw = self.frontmatter.get("scope", []) or []  # type: ignore[assignment]
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, list):
            return [str(s) for s in cast("list[Any]", raw)]
        return []

    @property
    def category(self) -> str | None:
        """Return the category directory name (e.g. 'concepts') or None for flat-layout pages."""
        parts = self.path.parts
        # Expected shape: .../pages/<category>/<slug>.md
        if "pages" in parts:
            idx = parts.index("pages")
            # If there's a dir between 'pages' and the file, that's the category.
            if idx + 2 < len(parts):
                return parts[idx + 1]
        return None
