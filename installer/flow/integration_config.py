# installer/flow/integration_config.py
"""prompt_toolkit replacement for Textual integration config screens.

Each service (Todoist, Trello, Jira) gets a configure_<service>(console)
function. All share _run_integration_form which handles:
 - submit
 - sync-disabled skip validation
 - synchronous httpx credential validation inside console.status()
 - re-prompt with pre-filled values + error banner on validation failure
 - cancel returns None

Existing yaml values pre-fill FieldSpec defaults so users never re-type
unchanged credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import httpx
import yaml
from rich.console import Console

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.flow.form import FieldSpec, run_form


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return load_existing_yaml(path) or {}
    except ConfigLoadError:
        return {}


def _run_integration_form(
    service_name: str,
    fields: list[FieldSpec],
    validator: Callable[[dict[str, Any]], str | None],
    console: Console,
) -> dict[str, Any] | None:
    """Shared form runner: submit → skip-if-disabled → validate → re-prompt on err."""
    error: str | None = None
    current_fields = fields
    while True:
        result = run_form(
            current_fields,
            console,
            title=f"{service_name} Configuration",
            error_message=error,
        )
        if result is None:
            return None
        # B2: skip validation when sync disabled
        if not result.get("sync_enabled", True):
            return result
        with console.status(f"Validating {service_name} credentials..."):
            error = validator(result)
        if error is None:
            return result
        # Re-build fields with current submitted values as defaults
        current_fields = [
            FieldSpec(
                key=f.key,
                label=f.label,
                kind=f.kind,
                default=result.get(f.key, f.default),
                choices=f.choices,
                validator=f.validator,
                help_text=f.help_text,
                group=f.group,
            )
            for f in current_fields
        ]


def _todoist_validator(values: dict[str, Any]) -> str | None:
    token = (values.get("api_token") or "").strip()
    if not token:
        return "API token is required"
    try:
        resp = httpx.get(
            "https://api.todoist.com/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 401:
            return "Invalid API token"
        if resp.status_code != 200:
            return f"Todoist API error: {resp.status_code}"
    except httpx.ConnectError:
        return "Cannot reach Todoist API — check network"
    except httpx.TimeoutException:
        return "Todoist API timeout"
    return None


def configure_todoist(console: Console) -> dict[str, Any] | None:
    """Todoist integration config form. Returns dict or None on cancel."""
    claude_home = Path.home() / ".claude"
    todoist_cfg = _load_yaml(claude_home / "todoist.yaml")
    proj_cfg = _load_yaml(claude_home / "proj.yaml")
    sync_section = (proj_cfg.get("sync", {}) or {}).get("todoist", {}) or {}

    fields = [
        FieldSpec(
            key="api_token",
            label="API Token",
            kind="password",
            default=(
                todoist_cfg.get("api_token") or sync_section.get("api_token") or ""
            ),
            help_text="Get from Settings > Integrations > API token in Todoist",
        ),
        FieldSpec(
            key="sync_enabled",
            label="Enable Todoist sync",
            kind="bool",
            default=bool(sync_section.get("enabled", False)),
        ),
        FieldSpec(
            key="auto_sync",
            label="Auto-sync on todo changes",
            kind="bool",
            default=bool(sync_section.get("auto_sync", True)),
        ),
        FieldSpec(
            key="root_only",
            label="Sync root-level todos only",
            kind="bool",
            default=bool(sync_section.get("root_only", False)),
        ),
    ]
    return _run_integration_form("Todoist", fields, _todoist_validator, console)


def _trello_validator(values: dict[str, Any]) -> str | None:
    key = (values.get("api_key") or "").strip()
    token = (values.get("token") or "").strip()
    if not key or not token:
        return "API key and token are both required"
    try:
        resp = httpx.get(
            f"https://api.trello.com/1/members/me?key={key}&token={token}",
            timeout=10,
        )
        if resp.status_code == 401:
            return "Invalid API key or token"
        if resp.status_code != 200:
            return f"Trello API error: {resp.status_code}"
    except httpx.ConnectError:
        return "Cannot reach Trello API — check network"
    except httpx.TimeoutException:
        return "Trello API timeout"
    return None


def configure_trello(console: Console) -> dict[str, Any] | None:
    """Trello integration config form. Returns dict or None on cancel."""
    claude_home = Path.home() / ".claude"
    trello_cfg = _load_yaml(claude_home / "trello.yaml")
    proj_cfg = _load_yaml(claude_home / "proj.yaml")
    sync_section = (proj_cfg.get("sync", {}) or {}).get("trello", {}) or {}

    default_list = str(sync_section.get("default_list") or "Todo")
    on_delete = str(sync_section.get("on_delete") or "archive")
    if on_delete not in ("archive", "delete"):
        on_delete = "archive"

    fields = [
        FieldSpec(
            key="api_key",
            label="API Key",
            kind="password",
            default=trello_cfg.get("api_key") or "",
            help_text="Get from https://trello.com/power-ups/admin/",
        ),
        FieldSpec(
            key="token",
            label="Token",
            kind="password",
            default=trello_cfg.get("token") or "",
        ),
        FieldSpec(
            key="sync_enabled",
            label="Enable Trello sync",
            kind="bool",
            default=bool(sync_section.get("enabled", False)),
        ),
        FieldSpec(
            key="auto_sync",
            label="Auto-sync on todo changes",
            kind="bool",
            default=bool(sync_section.get("auto_sync", True)),
        ),
        FieldSpec(
            key="default_list",
            label="Default Trello list name",
            kind="text",
            default=default_list,
        ),
        FieldSpec(
            key="on_delete",
            label="On delete",
            kind="select",
            default=on_delete,
            choices=["archive", "delete"],
        ),
    ]
    return _run_integration_form("Trello", fields, _trello_validator, console)


def _jira_base_url_validator(v: Any) -> str | None:
    v = (v or "").strip()
    if not v:
        return "Base URL is required"
    if not (v.startswith("http://") or v.startswith("https://")):
        return "must start with http:// or https://"
    return None


def _jira_validator(values: dict[str, Any]) -> str | None:
    base_url = (values.get("base_url") or "").strip().rstrip("/")
    token = (values.get("personal_access_token") or "").strip()
    if not base_url:
        return "Base URL is required"
    if not token:
        return "Personal access token is required"
    try:
        resp = httpx.get(
            f"{base_url}/rest/api/2/myself",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 401:
            return "Invalid personal access token"
        if resp.status_code != 200:
            return f"Jira API error: {resp.status_code}"
    except httpx.ConnectError:
        return f"Cannot reach {base_url} — check URL and network"
    except httpx.TimeoutException:
        return "Jira API timeout"
    return None


def _confluence_base_url_validator(v: Any) -> str | None:
    v = (v or "").strip()
    if not v:
        return "Base URL is required"
    if not (v.startswith("http://") or v.startswith("https://")):
        return "must start with http:// or https://"
    return None


def _confluence_validator(values: dict[str, Any]) -> str | None:
    from urllib.parse import urlparse

    base_url = (values.get("base_url") or "").strip().rstrip("/")
    deployment = values.get("deployment", "auto")
    if not base_url:
        return "Base URL is required"

    # Resolve effective deployment
    effective = deployment
    if effective == "auto":
        host = urlparse(base_url).hostname or ""
        effective = "cloud" if host.endswith(".atlassian.net") else "server"

    if effective == "cloud":
        email = (values.get("email") or "").strip()
        api_token = (values.get("api_token") or "").strip()
        if not email or not api_token:
            return "Email and API token are required for Cloud deployment"
        api_base = f"{base_url}/wiki/rest/api"
        auth: tuple[str, str] | None = (email, api_token)
        headers: dict[str, str] = {}
    else:
        pat = (values.get("personal_access_token") or "").strip()
        if not pat:
            return "Personal Access Token is required for Server/Data Center deployment"
        api_base = f"{base_url}/rest/api"
        auth = None
        headers = {"Authorization": f"Bearer {pat}"}

    try:
        resp = httpx.get(
            f"{api_base}/space",
            params={"limit": 1},
            auth=auth,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 401:
            return "Invalid credentials — check email/token"
        if resp.status_code == 403:
            return "Access forbidden — check permissions"
        if resp.status_code != 200:
            return f"Confluence API error: {resp.status_code}"
    except httpx.ConnectError:
        return f"Cannot reach {base_url} — check URL and network"
    except httpx.TimeoutException:
        return "Confluence API timeout"
    return None


def configure_confluence(console: Console) -> dict[str, Any] | None:
    """Confluence integration config form. Returns dict or None on cancel."""
    claude_home = Path.home() / ".claude"
    confluence_cfg = _load_yaml(claude_home / "confluence.yaml")
    proj_cfg = _load_yaml(claude_home / "proj.yaml")
    sync_section = (proj_cfg.get("sync", {}) or {}).get("confluence", {}) or {}

    fields = [
        FieldSpec(
            key="base_url",
            label="Base URL",
            kind="text",
            default=confluence_cfg.get("base_url") or "",
            help_text="e.g., https://example.atlassian.net or https://confluence.company.com",
            validator=_confluence_base_url_validator,
        ),
        FieldSpec(
            key="deployment",
            label="Deployment type",
            kind="select",
            default=confluence_cfg.get("deployment") or "auto",
            choices=["auto", "cloud", "server"],
            help_text="auto = detect from URL (.atlassian.net → cloud, else server)",
        ),
        FieldSpec(
            key="email",
            label="Email (Cloud only)",
            kind="text",
            default=confluence_cfg.get("email") or "",
            help_text="Atlassian account email — required for Cloud deployment",
        ),
        FieldSpec(
            key="api_token",
            label="API Token (Cloud only)",
            kind="password",
            default=confluence_cfg.get("api_token") or "",
            help_text="Get from https://id.atlassian.com/manage-profile/security/api-tokens",
        ),
        FieldSpec(
            key="personal_access_token",
            label="Personal Access Token (Server/DC only)",
            kind="password",
            default=confluence_cfg.get("personal_access_token") or "",
            help_text="Required for Server/Data Center deployment",
        ),
        FieldSpec(
            key="sync_enabled",
            label="Enable Confluence integration",
            kind="bool",
            default=bool(sync_section.get("enabled", False)),
        ),
    ]
    result = _run_integration_form("Confluence", fields, _confluence_validator, console)
    if result is None:
        return None
    # Normalize trailing slash on submit
    if "base_url" in result:
        result["base_url"] = (result["base_url"] or "").strip().rstrip("/")
    return result


def configure_jira(console: Console) -> dict[str, Any] | None:
    """Jira integration config form. Returns dict or None on cancel."""
    claude_home = Path.home() / ".claude"
    jira_cfg = _load_yaml(claude_home / "jira.yaml")
    proj_cfg = _load_yaml(claude_home / "proj.yaml")
    # proj.yaml uses "jira.<key>" (not "sync.jira.<key>")
    jira_section = proj_cfg.get("jira", {}) or {}

    fields = [
        FieldSpec(
            key="base_url",
            label="Base URL",
            kind="text",
            default=jira_cfg.get("base_url") or "",
            help_text="e.g., https://yourcompany.atlassian.net",
            validator=_jira_base_url_validator,
        ),
        FieldSpec(
            key="default_user",
            label="Username / Email",
            kind="text",
            default=jira_cfg.get("default_user") or "",
        ),
        FieldSpec(
            key="personal_access_token",
            label="Personal Access Token",
            kind="password",
            default=jira_cfg.get("personal_access_token") or "",
        ),
        FieldSpec(
            key="default_project",
            label="Default Project Key",
            kind="text",
            default=jira_cfg.get("default_project") or "",
            help_text="e.g., PROJ, TEAM",
        ),
        FieldSpec(
            key="sync_enabled",
            label="Enable Jira sync",
            kind="bool",
            default=bool(jira_section.get("enabled", False)),
        ),
        FieldSpec(
            key="auto_sync",
            label="Auto-sync on todo changes",
            kind="bool",
            default=bool(jira_section.get("auto_sync", True)),
        ),
    ]
    result = _run_integration_form("Jira", fields, _jira_validator, console)
    if result is None:
        return None
    # B3 fix: normalize trailing slash on submit
    if "base_url" in result:
        result["base_url"] = (result["base_url"] or "").strip().rstrip("/")
    return result


def configure_wiki(
    console: Console, proj_selected: bool = False
) -> dict[str, Any] | None:
    """Wiki integration config form. Returns dict or None on cancel.

    No credential validation (wiki has no auth). Extra fields appear only when
    proj is also being installed (for the sync.wiki.* gating flags).
    """
    claude_home = Path.home() / ".claude"
    wiki_yaml = _load_yaml(claude_home / "wiki.yaml")
    wiki_config_yaml = _load_yaml(claude_home / "wiki" / "config.yaml")
    proj_yaml = _load_yaml(claude_home / "proj.yaml")
    proj_sync_wiki = (proj_yaml.get("sync", {}) or {}).get("wiki", {}) or {}

    fields = [
        FieldSpec(
            key="enabled",
            label="Enable wiki plugin",
            kind="bool",
            default=bool(wiki_yaml.get("enabled", False)),
            help_text="Master switch. Wiki MCP server serves requests when enabled.",
        ),
        FieldSpec(
            key="profile",
            label="Category profile",
            kind="select",
            choices=["software", "personal", "research", "minimal", "custom"],
            default=str(wiki_config_yaml.get("profile", "software")),
            help_text=(
                "software: concepts/decisions/references/pitfalls/entities. "
                "personal: journal/topics/people/places/lessons. "
                "research: concepts/sources/findings/questions. "
                "minimal: flat pages/, no subdirs. "
                "custom: you define categories."
            ),
        ),
        FieldSpec(
            key="custom_categories",
            label="Custom categories (comma-separated, only used if profile=custom)",
            kind="text",
            default=",".join(wiki_config_yaml.get("categories", []) or []),
            help_text="Leave blank unless you picked 'custom' profile.",
        ),
        FieldSpec(
            key="bootstrap_pending",
            label="Queue /wiki:bootstrap for next session?",
            kind="bool",
            default=bool(wiki_yaml.get("bootstrap_pending", False)),
            help_text=(
                "If yes, sets a flag that prompts you on next Claude session. "
                "The wizard cannot invoke LLM-driven skills directly."
            ),
        ),
    ]
    if proj_selected:
        fields.extend(
            [
                FieldSpec(
                    key="proj_auto_ingest_sessions",
                    label="[proj] Auto-ingest /proj:save sessions into wiki",
                    kind="bool",
                    default=bool(proj_sync_wiki.get("auto_ingest_sessions", False)),
                    help_text="Final step of /proj:save spawns wiki ingest subagent on session file.",
                ),
                FieldSpec(
                    key="proj_capture_notes_as_log",
                    label="[proj] Capture notes_append as wiki log entries",
                    kind="bool",
                    default=bool(proj_sync_wiki.get("capture_notes_as_log", False)),
                    help_text="Router hook: every notes_append also appends a wiki log entry.",
                ),
            ]
        )

    # No validator; pass a no-op function
    return _run_integration_form("Wiki", fields, lambda _: None, console)


def _write_wiki_integration_result(result: dict[str, Any], proj_selected: bool) -> None:
    """Write wiki config to 3 files + create category subdirs per profile.

    Also seeds index.md + log.md so the wiki is immediately usable after
    install — avoids the deadlock where /wiki:init refuses (wiki.yaml exists)
    and /wiki:bootstrap refuses (empty index).
    """
    from datetime import date

    claude_home = Path.home() / ".claude"
    wiki_home = claude_home / "wiki"
    wiki_home.mkdir(parents=True, exist_ok=True)
    (wiki_home / "pages").mkdir(exist_ok=True)

    # Seed index.md with empty index (mirrors wiki_index_rebuild on zero pages).
    index_path = wiki_home / "index.md"
    if not index_path.exists():
        index_path.write_text("# Wiki Index\n")

    # Seed log.md with installer-init entry (mirrors wiki_log_append format).
    log_path = wiki_home / "log.md"
    if not log_path.exists():
        today = date.today().isoformat()
        log_path.write_text(f"## [{today}] init | installer-seeded\n\n")

    # 1. ~/.claude/wiki.yaml — preserve non-wizard keys
    wiki_yaml_path = claude_home / "wiki.yaml"
    existing_wiki = _load_yaml(wiki_yaml_path)
    existing_wiki["enabled"] = bool(result["enabled"])
    existing_wiki["wiki_dir"] = str(wiki_home)
    existing_wiki.setdefault("reingest_cooldown_hours", 24)
    # Wiki is now seeded — bootstrap_pending cleared regardless of form value.
    existing_wiki["bootstrap_pending"] = False
    existing_wiki.setdefault("session_ingest", {"section_map": {}})
    _atomic_write_yaml(wiki_yaml_path, existing_wiki)

    # 2. ~/.claude/wiki/config.yaml
    profile = str(result.get("profile", "software"))
    config_yaml_path = wiki_home / "config.yaml"
    config_data: dict[str, Any] = {
        "schema_version": 1,
        "profile": profile,
        "required_frontmatter": [
            "title",
            "tags",
            "links_to",
            "scope",
            "sources",
            "last_ingested",
        ],
        "lint": {
            "stale_after_days": 90,
            "orphan_min_page_count": 3,
        },
    }
    if profile == "custom":
        raw = str(result.get("custom_categories", "") or "")
        cats = [c.strip() for c in raw.split(",") if c.strip()]
        if not cats:
            cats = ["notes"]
        config_data["categories"] = cats
    _atomic_write_yaml(config_yaml_path, config_data)

    # 3. Create category subdirs per profile
    cat_map: dict[str, list[str]] = {
        "software": ["concepts", "decisions", "references", "pitfalls", "entities"],
        "personal": ["journal", "topics", "people", "places", "lessons"],
        "research": ["concepts", "sources", "findings", "questions"],
        "minimal": [],
    }
    if profile == "custom":
        categories = config_data.get("categories", [])
        if isinstance(categories, list):
            cat_map["custom"] = [str(c) for c in categories]
        else:
            cat_map["custom"] = []
    for cat in cat_map.get(profile, []):
        (wiki_home / "pages" / cat).mkdir(exist_ok=True)

    # 4. proj.yaml sync.wiki.* (only if proj is also being installed)
    if proj_selected:
        proj_yaml_path = claude_home / "proj.yaml"
        existing_proj = _load_yaml(proj_yaml_path)
        sync = existing_proj.setdefault("sync", {})
        existing_wiki_sync = sync.get("wiki", {}) or {}
        sync["wiki"] = {
            "enabled": bool(result["enabled"]),
            "auto_sync": True,
            "auto_ingest_sessions": bool(
                result.get("proj_auto_ingest_sessions", False)
            ),
            "capture_notes_as_log": bool(
                result.get("proj_capture_notes_as_log", False)
            ),
            "replace_notes_md": bool(existing_wiki_sync.get("replace_notes_md", False)),
            "bootstrap_docs": existing_wiki_sync.get("bootstrap_docs", []) or [],
        }
        _atomic_write_yaml(proj_yaml_path, existing_proj)


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomic yaml write via tmpfile + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    tmp.replace(path)
