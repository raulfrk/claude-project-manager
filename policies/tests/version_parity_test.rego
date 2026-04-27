package cpm.version_parity_test

import data.cpm.version_parity
import rego.v1

test_match_passes if {
	result := version_parity.deny with input as {
		"plugins": [{"name": "proj", "version": "5.1.8"}],
	}
		with data.plugin_jsons as {"proj": {"version": "5.1.8"}}
	count(result) == 0
}

test_drift_detected if {
	result := version_parity.deny with input as {
		"plugins": [{"name": "proj", "version": "5.1.8"}],
	}
		with data.plugin_jsons as {"proj": {"version": "5.1.7"}}
	count(result) == 1
}

test_multi_plugin_partial_drift if {
	result := version_parity.deny with input as {"plugins": [
		{"name": "proj", "version": "5.1.8"},
		{"name": "worktree", "version": "5.0.1"},
	]}
		with data.plugin_jsons as {
			"proj": {"version": "5.1.8"},
			"worktree": {"version": "5.0.0"},
		}
	count(result) == 1
}
