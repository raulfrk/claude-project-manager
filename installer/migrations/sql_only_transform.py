# installer/migrations/sql_only_transform.py
"""Wizard's v2→v3 YAML→SQL transform.

Delegates to the proj plugin's canonical `migrate_yaml_to_sqlite`.

Why we cross the installer↔plugin boundary here:
The wizard previously hand-rolled a parallel YAML→SQL transform that
silently drifted from the real `Todo` schema. The drift caused a chain of
data-loss bugs (data.db existence guard, dict-bind on trello_sync_state,
missing meta.yaml migration, mismatched field names: `git`/`git_branch`,
`jira_synced_comment_ids`/`jira_comment_ids`,
`todoist_description_synced`/`todoist_desc_synced`). To make this class
of bug impossible, the wizard now delegates to the single source of truth
in `plugins/proj/server/server/lib/migration.py`. Any future field added
to `Todo` flows through automatically.

Source-tree assumption: `cpm-install` is documented as `uvx --from
git+...` or `uv run cpm-install`, both of which run from a checked-out
repo where `plugins/proj/server` sits next to `installer/`. A pure-PyPI
wheel install would not work — we fail fast with an actionable message.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Repo layout: installer/migrations/sql_only_transform.py → repo root is parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROJ_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "proj" / "server"


def _normalize_wrapped_yaml(path: Path) -> None:
    """Rewrite a bare-list YAML file as a `{"todos": [...]}` wrapper in
    place. No-op if the file is missing, already wrapped, or empty.

    The proj plugin's runtime migrate accepts only the wrapped form (the
    canonical shape produced by current writers). Older proj versions and
    test fixtures sometimes emit bare lists; we normalise them here so the
    runtime can read them.
    """
    if not path.exists():
        return
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return
    if not isinstance(raw, list):
        return  # already wrapped, scalar, or None
    path.write_text(yaml.safe_dump({"todos": raw}, sort_keys=False))


def migrate_yaml_to_sql(project_dir: Path) -> None:
    """Migrate a v2 project's YAML files into its data.db.

    Delegates to `server.lib.migration.migrate_yaml_to_sqlite` so the
    transform stays in lock-step with the proj plugin's canonical schema.

    Idempotent. Reads todos.yaml + archive.yaml + meta.yaml +
    decisions.yaml; populates todos / archive_todos / project_meta /
    decisions tables (creating data.db if absent); renames migrated YAML
    files to `<name>.bak` for disaster recovery.
    Raises on SQL errors (caller should roll back / restore backup).
    """
    if not _PROJ_PLUGIN_ROOT.is_dir():
        raise RuntimeError(
            f"cannot find proj plugin source at {_PROJ_PLUGIN_ROOT}; "
            "cpm-install must be run from a source checkout (e.g. "
            "`uvx --from git+https://github.com/raulfrk/claude-project-manager "
            "cpm-install`)"
        )

    # Normalise legacy bare-list YAML into the wrapped form the runtime expects.
    _normalize_wrapped_yaml(project_dir / "todos.yaml")
    _normalize_wrapped_yaml(project_dir / "archive.yaml")

    if str(_PROJ_PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJ_PLUGIN_ROOT))

    from server.lib.migration import migrate_yaml_to_sqlite
    from server.lib.models import ProjConfig

    cfg = ProjConfig(tracking_dir=str(project_dir.parent))
    migrate_yaml_to_sqlite(cfg, project_dir.name)
