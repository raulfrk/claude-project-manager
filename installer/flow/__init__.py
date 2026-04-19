# installer/flow/__init__.py
"""Plain-Python flow helpers that drive the installer without Textual.

Each helper takes an `InstallState` (or similar) and a `rich.Console`, prompts
or reports via Rich (and later prompt_toolkit), and returns updated state.
"""
