"""Data models for worktree configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BaseRepo:
    label: str
    path: str  # absolute path as string
    default_branch: str = "main"

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "path": self.path,
            "default_branch": self.default_branch,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> BaseRepo:
        return cls(
            label=data["label"],
            path=data["path"],
            default_branch=data.get("default_branch", "main"),
        )


@dataclass
class WorktreeEntry:
    """Represents a single git worktree."""

    path: str
    branch: str
    head: str
    bare: bool = False
    detached: bool = False
    locked: bool = False
    prunable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "branch": self.branch,
            "head": self.head,
            "bare": self.bare,
            "detached": self.detached,
            "locked": self.locked,
            "prunable": self.prunable,
        }


@dataclass
class WorktreeConfig:
    default_worktree_dir: str = "~/worktrees"
    base_repos: list[BaseRepo] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "default_worktree_dir": self.default_worktree_dir,
            "base_repos": [r.to_dict() for r in self.base_repos],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> WorktreeConfig:
        repos_raw = data.get("base_repos", [])
        if not isinstance(repos_raw, list):
            repos_raw = []
        return cls(
            default_worktree_dir=str(data.get("default_worktree_dir", "~/worktrees")),
            base_repos=[BaseRepo.from_dict(r) for r in repos_raw],  # type: ignore[arg-type]  # list[object] from YAML; items are dicts at runtime
        )
