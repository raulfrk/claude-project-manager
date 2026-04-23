"""Tests for lib/storage.py."""

import threading
from pathlib import Path

import pytest

from server.lib.storage import (
    atomic_write,
    page_path,
    pages_dir,
    wiki_lock,
    with_wiki_lock,
)


class TestPathHelpers:
    def test_pages_dir(self, wiki_root: Path) -> None:
        assert pages_dir(wiki_root) == wiki_root / "pages"

    def test_page_path_with_category(self, wiki_root: Path) -> None:
        assert (
            page_path(wiki_root, "concepts", "hooks")
            == wiki_root / "pages" / "concepts" / "hooks.md"
        )

    def test_page_path_without_category(self, wiki_root: Path) -> None:
        # minimal profile: pages/ is flat
        assert page_path(wiki_root, None, "hooks") == wiki_root / "pages" / "hooks.md"


class TestAtomicWrite:
    def test_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir" / "f.md"
        atomic_write(target, "content")
        assert target.read_text() == "content"

    def test_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "f.md"
        target.write_text("old")
        atomic_write(target, "new")
        assert target.read_text() == "new"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c.md"
        atomic_write(target, "x")
        assert target.exists()


class TestWikiLock:
    def test_lock_is_reentrant_within_thread(self, wiki_root: Path) -> None:
        # `with wiki_lock()` must allow recursive acquisition from the same thread
        with wiki_lock(wiki_root), wiki_lock(wiki_root):  # should NOT deadlock
            (wiki_root / "x.md").write_text("ok")
        assert (wiki_root / "x.md").exists()

    def test_with_wiki_lock_decorator(self, wiki_root: Path) -> None:
        @with_wiki_lock
        def op(wiki_dir: Path, name: str) -> str:
            (wiki_dir / f"{name}.md").write_text(name)
            return name

        assert op(wiki_root, "foo") == "foo"
        assert (wiki_root / "foo.md").exists()

    def test_lock_blocks_other_thread(self, wiki_root: Path) -> None:
        import time

        order: list[str] = []

        def worker_a() -> None:
            with wiki_lock(wiki_root):
                order.append("A-enter")
                time.sleep(0.1)
                order.append("A-exit")

        def worker_b() -> None:
            time.sleep(0.02)  # start slightly after A
            with wiki_lock(wiki_root):
                order.append("B-enter")
                order.append("B-exit")

        t_a = threading.Thread(target=worker_a)
        t_b = threading.Thread(target=worker_b)
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()
        assert order == ["A-enter", "A-exit", "B-enter", "B-exit"]


class TestAtomicWriteCleanup:
    def test_atomic_write_cleans_up_tmp_on_replace_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If os.replace (Path.replace) raises, the tmp file must be removed."""
        target = tmp_path / "target.md"

        original_replace = Path.replace

        def boom(self: Path, *args: object, **kwargs: object) -> Path:
            # Only boom for the atomic_write tmp file; let other replace calls through.
            if self.name.startswith(".target.md."):
                raise OSError("simulated replace failure")
            return original_replace(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "replace", boom)

        with pytest.raises(OSError, match="simulated replace failure"):
            atomic_write(target, "hello")

        # Target was never created (the replace failed).
        assert not target.exists()
        # Tmp file must have been cleaned up.
        tmp_leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".target.md.")]
        assert tmp_leftovers == [], f"leaked tmp files: {tmp_leftovers}"
