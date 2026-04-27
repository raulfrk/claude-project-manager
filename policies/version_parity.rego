package cpm.version_parity

import rego.v1

# Asserts plugin.json::version == marketplace.json::plugins[name].version.
#
# Two input shapes supported:
# 1. `--combine` mode: input is array of {contents, path} entries (one per file).
#    The marketplace.json entry has a `plugins` array; each plugin.json has
#    `name` + `version`.
# 2. Direct mode: input has `plugins` (marketplace) and data.plugin_jsons keyed
#    by plugin name (used in unit tests).

# --- Combine-mode (production) ---

# Extract the marketplace.json entry from the combined input array.
marketplace_entry := entry if {
	some entry in input
	entry.contents.plugins
}

# Build a lookup of {plugin_name: version} from per-plugin.json entries.
plugin_versions[name] := version if {
	some entry in input
	entry.contents.name
	entry.contents.version
	# Skip the marketplace entry (which also has a `name` at top level — the
	# marketplace name "claude-project-manager" is not a plugin name).
	not entry.contents.plugins
	name := entry.contents.name
	version := entry.contents.version
}

deny contains msg if {
	some plugin in marketplace_entry.contents.plugins
	declared := plugin_versions[plugin.name]
	declared != plugin.version
	msg := sprintf(
		"version drift: %s plugin.json=%s but marketplace.json=%s",
		[plugin.name, declared, plugin.version],
	)
}

# --- Direct-mode (unit tests) ---

deny contains msg if {
	some entry in input.plugins
	plugin_json := data.plugin_jsons[entry.name]
	plugin_json.version != entry.version
	msg := sprintf(
		"version drift: %s plugin.json=%s but marketplace.json=%s",
		[entry.name, plugin_json.version, entry.version],
	)
}
