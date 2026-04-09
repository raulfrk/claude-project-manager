#!/usr/bin/env bash
# claude-stub.sh — stub fallback that mimics `claude plugin` CLI outputs.
# Designed as a prepared fallback if real Claude CLI requires auth for plugin
# commands during e2e testing. NOT auto-activated.
#
# State is persisted in $TMPDIR/claude-stub-state.json so install/uninstall
# operations are reflected in subsequent list queries.

set -euo pipefail

STATE_FILE="${TMPDIR:-/tmp}/claude-stub-state.json"
MARKETPLACE_NAME="claude-project-manager"

ALL_PLUGINS=(sandbox hooks proj worktree zoxide analyse todoist trello jira)

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

_init_state() {
    if [[ ! -f "$STATE_FILE" ]]; then
        printf '{"installed":[]}\n' > "$STATE_FILE"
    fi
}

_read_installed() {
    _init_state
    # Returns the installed array as newline-separated IDs
    python3 -c "
import json, sys
with open('$STATE_FILE') as f:
    data = json.load(f)
for p in data.get('installed', []):
    print(p)
"
}

_add_installed() {
    local plugin_id="$1"
    _init_state
    python3 -c "
import json
with open('$STATE_FILE') as f:
    data = json.load(f)
installed = data.get('installed', [])
if '$plugin_id' not in installed:
    installed.append('$plugin_id')
data['installed'] = installed
with open('$STATE_FILE', 'w') as f:
    json.dump(data, f)
"
}

_remove_installed() {
    local plugin_id="$1"
    _init_state
    python3 -c "
import json
with open('$STATE_FILE') as f:
    data = json.load(f)
installed = [p for p in data.get('installed', []) if p != '$plugin_id']
data['installed'] = installed
with open('$STATE_FILE', 'w') as f:
    json.dump(data, f)
"
}

# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

cmd_marketplace_list() {
    echo "  > $MARKETPLACE_NAME"
    exit 0
}

cmd_marketplace_add() {
    # Usage: claude plugin marketplace add <ref>
    exit 0
}

cmd_marketplace_remove() {
    # Usage: claude plugin marketplace remove <name>
    exit 0
}

cmd_plugin_list_json() {
    _init_state
    python3 -c "
import json
with open('$STATE_FILE') as f:
    data = json.load(f)
installed = data.get('installed', [])
result = {'installed': [{'id': pid} for pid in installed]}
print(json.dumps(result))
"
    exit 0
}

cmd_plugin_list_available_json() {
    local plugins_json="["
    local first=true
    for p in "${ALL_PLUGINS[@]}"; do
        if [ "$first" = true ]; then
            first=false
        else
            plugins_json+=","
        fi
        plugins_json+="{\"pluginId\":\"${p}@${MARKETPLACE_NAME}\"}"
    done
    plugins_json+="]"
    echo "{\"available\":${plugins_json}}"
    exit 0
}

cmd_plugin_install() {
    local plugin_id="$1"
    _add_installed "$plugin_id"
    exit 0
}

cmd_plugin_update() {
    # Usage: claude plugin update <id>
    exit 0
}

cmd_plugin_uninstall() {
    local plugin_id="$1"
    _remove_installed "$plugin_id"
    exit 0
}

# ---------------------------------------------------------------------------
# Argument routing
# ---------------------------------------------------------------------------

# Expect: claude plugin <subcommand> [args...]
# When used as a stub, argv[0] replaces "claude", so we start parsing at $1.

if [[ "${1:-}" != "plugin" ]]; then
    echo "claude-stub: unsupported command: $*" >&2
    exit 1
fi
shift  # consume "plugin"

case "${1:-}" in
    marketplace)
        shift
        case "${1:-}" in
            list)
                cmd_marketplace_list
                ;;
            add)
                shift
                cmd_marketplace_add "$@"
                ;;
            remove)
                shift
                cmd_marketplace_remove "$@"
                ;;
            *)
                echo "claude-stub: unsupported marketplace subcommand: ${1:-}" >&2
                exit 1
                ;;
        esac
        ;;
    list)
        shift
        # Detect --available --json vs --json
        has_available=false
        has_json=false
        for arg in "$@"; do
            case "$arg" in
                --available) has_available=true ;;
                --json) has_json=true ;;
            esac
        done
        if $has_json && $has_available; then
            cmd_plugin_list_available_json
        elif $has_json; then
            cmd_plugin_list_json
        else
            echo "claude-stub: plugin list requires --json" >&2
            exit 1
        fi
        ;;
    install)
        shift
        cmd_plugin_install "${1:?missing plugin id}"
        ;;
    update)
        shift
        cmd_plugin_update "${1:?missing plugin id}"
        ;;
    uninstall)
        shift
        cmd_plugin_uninstall "${1:?missing plugin id}"
        ;;
    *)
        echo "claude-stub: unsupported plugin subcommand: ${1:-}" >&2
        exit 1
        ;;
esac
