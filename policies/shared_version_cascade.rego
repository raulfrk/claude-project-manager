package cpm.shared_version_cascade

import rego.v1

# Input is the JSON dumped by scripts/_gather_shared_version_state.py:
# {
#   "shared_py_staged": [...],
#   "head_version": "0.4.39",
#   "staged_version": "0.4.40",
#   "lockfiles": {"<path>": "0.4.40", ...}
# }

# Rule A: _shared .py staged but pyproject.toml version not bumped.
deny contains msg if {
	count(input.shared_py_staged) > 0
	input.staged_version == input.head_version
	msg := sprintf(
		"_shared .py files staged but pyproject.toml version not bumped (still %s). Bump version + run `just sync`.",
		[input.staged_version],
	)
}

# Rule B1: version was bumped but lockfile pins a different version.
deny contains msg if {
	count(input.shared_py_staged) > 0
	input.staged_version != input.head_version
	some path, actual in input.lockfiles
	actual != null
	actual != input.staged_version
	msg := sprintf(
		"lockfile drift: %s pins claude-hook-transport=%v but staged _shared version is %s. Run `just sync` then re-stage.",
		[path, actual, input.staged_version],
	)
}

# Rule B2: version was bumped but lockfile is missing or unparseable.
deny contains msg if {
	count(input.shared_py_staged) > 0
	input.staged_version != input.head_version
	some path, actual in input.lockfiles
	actual == null
	msg := sprintf(
		"lockfile missing or unparseable: %s — run `just sync` to regenerate.",
		[path],
	)
}
