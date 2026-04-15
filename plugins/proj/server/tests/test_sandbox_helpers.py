"""Tests for server.lib.sandbox_helpers."""

from dataclasses import dataclass, field
from pathlib import Path

from server.lib.sandbox_helpers import project_dir_from_meta, project_dirs_from_meta


@dataclass
class FakeRepo:
    label: str = "code"
    path: str = "/home/user/project"
    reference: bool = False


@dataclass
class FakeMeta:
    repos: list = field(default_factory=list)


class TestProjectDirsFromMeta:
    def test_non_reference_repos(self):
        meta = FakeMeta(
            repos=[
                FakeRepo(path="/a", reference=False),
                FakeRepo(path="/b", reference=True),
                FakeRepo(path="/c", reference=False),
            ]
        )
        dirs = project_dirs_from_meta(meta)
        assert dirs == [Path("/a"), Path("/c")]

    def test_all_reference_falls_back_to_first(self):
        meta = FakeMeta(
            repos=[
                FakeRepo(path="/ref1", reference=True),
                FakeRepo(path="/ref2", reference=True),
            ]
        )
        dirs = project_dirs_from_meta(meta)
        assert dirs == [Path("/ref1")]

    def test_empty_repos(self):
        meta = FakeMeta(repos=[])
        assert project_dirs_from_meta(meta) == []

    def test_single_non_reference(self):
        meta = FakeMeta(repos=[FakeRepo(path="/only")])
        assert project_dirs_from_meta(meta) == [Path("/only")]


class TestProjectDirFromMeta:
    def test_returns_first_non_reference(self):
        meta = FakeMeta(
            repos=[
                FakeRepo(path="/a", reference=True),
                FakeRepo(path="/b", reference=False),
            ]
        )
        assert project_dir_from_meta(meta) == Path("/b")

    def test_returns_none_when_empty(self):
        meta = FakeMeta(repos=[])
        assert project_dir_from_meta(meta) is None
