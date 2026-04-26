"""Tests for wiki_lock W1 fix: anyio.Lock + LOCK_NB + WikiLockTimeoutError."""

from __future__ import annotations

import fcntl
import multiprocessing
import os
import time
from pathlib import Path

import anyio
import pytest

from server.lib.storage import (
    WikiLockReentryError,
    WikiLockTimeoutError,
    _flock_with_timeout,
    wiki_lock,
)


@pytest.fixture
def fast_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lower the 30s production timeout to 0.5s for fast unit tests."""
    monkeypatch.setattr("server.lib.storage.WIKI_LOCK_TIMEOUT", 0.5)


def _hold_flock_subprocess(lock_path: str, hold_s: float, ready_path: str) -> None:
    """Subprocess helper: open lock_path, take fcntl flock, signal ready, sleep, release."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    Path(ready_path).touch()
    time.sleep(hold_s)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


class TestExceptionClasses:
    def test_wiki_lock_timeout_error_importable(self) -> None:
        from server.lib.storage import WikiLockTimeoutError

        assert issubclass(WikiLockTimeoutError, RuntimeError)

    def test_wiki_lock_reentry_error_importable(self) -> None:
        from server.lib.storage import WikiLockReentryError

        assert issubclass(WikiLockReentryError, RuntimeError)

    def test_constants_default(self) -> None:
        from server.lib.storage import WIKI_LOCK_RETRY_INTERVAL, WIKI_LOCK_TIMEOUT

        assert WIKI_LOCK_TIMEOUT == 30.0
        assert WIKI_LOCK_RETRY_INTERVAL == 0.1


class TestFlockWithTimeout:
    def test_acquires_immediately_when_uncontended(self, tmp_path: Path) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        fd = os.open(str(lock_path), os.O_RDWR)
        try:
            start = time.monotonic()
            _flock_with_timeout(fd, lock_path)
            elapsed = time.monotonic() - start
            assert elapsed < 0.05
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_raises_timeout_when_subprocess_holds(self, tmp_path: Path, fast_timeout: None) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=_hold_flock_subprocess, args=(str(lock_path), 2.0, str(ready)))
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                time.sleep(0.02)
            assert ready.exists()

            fd = os.open(str(lock_path), os.O_RDWR)
            try:
                with pytest.raises(WikiLockTimeoutError, match="not acquired within"):
                    _flock_with_timeout(fd, lock_path)
            finally:
                os.close(fd)
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()


class TestWikiLockAsync:
    @pytest.mark.anyio()
    async def test_no_contention_acquires_immediately(self, tmp_path: Path) -> None:
        start = time.monotonic()
        async with wiki_lock(tmp_path):
            pass
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    @pytest.mark.anyio()
    async def test_two_tasks_serialize(self, tmp_path: Path) -> None:
        log: list[str] = []

        async def hold(name: str, hold_seconds: float) -> None:
            log.append(f"{name} REQUEST {time.monotonic():.3f}")
            async with wiki_lock(tmp_path):
                log.append(f"{name} ENTER {time.monotonic():.3f}")
                await anyio.sleep(hold_seconds)
                log.append(f"{name} EXIT {time.monotonic():.3f}")

        async with anyio.create_task_group() as tg:
            tg.start_soon(hold, "A", 0.5)
            await anyio.sleep(0.05)
            tg.start_soon(hold, "B", 0.5)

        a_enter = next(i for i, x in enumerate(log) if x.startswith("A ENTER"))
        a_exit = next(i for i, x in enumerate(log) if x.startswith("A EXIT"))
        b_enter = next(i for i, x in enumerate(log) if x.startswith("B ENTER"))
        assert a_enter < a_exit < b_enter, f"B entered before A exited: {log}"

    @pytest.mark.anyio()
    async def test_reentry_raises(self, tmp_path: Path) -> None:
        async with wiki_lock(tmp_path):
            with pytest.raises(WikiLockReentryError, match="nested wiki_lock"):
                async with wiki_lock(tmp_path):
                    pass

    @pytest.mark.anyio()
    async def test_cross_process_blocks_until_released(self, tmp_path: Path) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=_hold_flock_subprocess, args=(str(lock_path), 1.0, str(ready)))
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                await anyio.sleep(0.02)
            assert ready.exists()

            start = time.monotonic()
            async with wiki_lock(tmp_path):
                elapsed = time.monotonic() - start
                assert elapsed > 0.5, f"acquired too fast: {elapsed}"
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join()

    @pytest.mark.anyio()
    async def test_cross_process_timeout_raises(self, tmp_path: Path, fast_timeout: None) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=_hold_flock_subprocess, args=(str(lock_path), 2.0, str(ready)))
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                await anyio.sleep(0.02)
            assert ready.exists()

            with pytest.raises(WikiLockTimeoutError, match="not acquired within"):
                async with wiki_lock(tmp_path):
                    pass
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()


class TestEventLoopResponsiveness:
    @pytest.mark.anyio()
    async def test_event_loop_responsive_during_index_rebuild(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """While wiki_index_rebuild runs, concurrent anyio sleeps complete fast."""
        from dataclasses import replace

        from server.lib import config as config_mod
        from server.lib.models import WikiConfig
        from server.tools.index import wiki_index_rebuild

        cfg_path = tmp_path / "wiki.yaml"
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "pages").mkdir()
        monkeypatch.setattr(config_mod, "_DEFAULT_CONFIG_PATH", cfg_path)
        config_mod.save_config(WikiConfig(enabled=True, wiki_dir=wiki_dir))
        # Avoid touching real config
        original_load = config_mod.load_config
        monkeypatch.setattr(
            config_mod,
            "load_config",
            lambda: replace(original_load(), wiki_dir=wiki_dir),
        )

        # Populate w/ enough pages so rebuild stays in flight long enough for
        # quick_op tasks to schedule + complete. 500 pages keeps rebuild busy
        # for hundreds of ms even on fast hardware (was 50; that finished too
        # fast on some systems leaving elapsed_for_quick empty + masking
        # regressions silently).
        pages = wiki_dir / "pages" / "concepts"
        pages.mkdir(parents=True)
        for i in range(500):
            (pages / f"page-{i}.md").write_text(
                f"---\ntitle: page-{i}\ntags: []\nlinks_to: []\nscope: []\n"
                f"sources: []\nlast_ingested: 2026-04-26\n---\nbody-{i}\n"
            )

        elapsed_for_quick: list[float] = []

        async def quick_op() -> None:
            start = time.monotonic()
            await anyio.sleep(0.001)
            elapsed_for_quick.append(time.monotonic() - start)

        async with anyio.create_task_group() as tg:
            tg.start_soon(wiki_index_rebuild)
            await anyio.sleep(0.05)  # let rebuild start
            for _ in range(10):
                tg.start_soon(quick_op)

        # Hard assert quick_op tasks ran — empty list means rebuild finished
        # before any quick_op was scheduled, which means the responsiveness
        # check itself didn't run + silently masks regressions.
        assert len(elapsed_for_quick) > 0, (
            "responsiveness test no-op: quick_op tasks never ran during rebuild "
            "(rebuild finished too fast). Increase page count."
        )
        assert max(elapsed_for_quick) < 0.5, (
            f"event loop stalled (max quick op took {max(elapsed_for_quick):.3f}s, "
            f"all values: {elapsed_for_quick})"
        )
