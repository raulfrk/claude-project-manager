"""Shared test configuration for hook_transport tests."""

import pytest


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    """Use asyncio backend only for anyio tests."""
    return request.param
