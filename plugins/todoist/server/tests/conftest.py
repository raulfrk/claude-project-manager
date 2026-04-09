"""Shared test configuration — adds tests/ directory to sys.path for contract imports."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `from contracts.tasks import ...` etc. inside test files.
_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
