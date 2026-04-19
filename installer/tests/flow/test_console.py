# installer/tests/flow/test_console.py
from rich.console import Console

from installer.flow.console import get_console, reset_console


def test_get_console_returns_rich_console() -> None:
    reset_console()
    c = get_console()
    assert isinstance(c, Console)


def test_get_console_is_singleton() -> None:
    reset_console()
    assert get_console() is get_console()


def test_reset_console_clears_singleton() -> None:
    first = get_console()
    reset_console()
    second = get_console()
    assert first is not second
