"""Tests for lib/storage.py."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from server.lib.storage import (
    WikiLockReentryError,
    atomic_write,
    page_path,
    pages_dir,
    wiki_lock,
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
    @pytest.mark.anyio()
    async def test_lock_is_not_reentrant_within_task(self, wiki_root: Path) -> None:
        """Post-W1: anyio.Lock is non-reentrant. Nested same-task acquire raises."""
        async with wiki_lock(wiki_root):
            with pytest.raises(WikiLockReentryError, match="nested wiki_lock"):
                async with wiki_lock(wiki_root):
                    pass

    @pytest.mark.anyio()
    async def test_lock_blocks_other_task(self, wiki_root: Path) -> None:
        order: list[str] = []

        async def worker_a() -> None:
            async with wiki_lock(wiki_root):
                order.append("A-enter")
                await anyio.sleep(0.1)
                order.append("A-exit")

        async def worker_b() -> None:
            await anyio.sleep(0.02)  # start slightly after A
            async with wiki_lock(wiki_root):
                order.append("B-enter")
                order.append("B-exit")

        async with anyio.create_task_group() as tg:
            tg.start_soon(worker_a)
            tg.start_soon(worker_b)

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
