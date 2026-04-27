package cpm.shared_version_cascade_test

import data.cpm.shared_version_cascade
import rego.v1

test_no_shared_change_passes if {
	result := shared_version_cascade.deny with input as {
		"shared_py_staged": [],
		"head_version": "0.4.39",
		"staged_version": "0.4.39",
		"lockfiles": {"uv.lock": "0.4.39"},
	}
	count(result) == 0
}

test_shared_change_no_bump_denied if {
	result := shared_version_cascade.deny with input as {
		"shared_py_staged": ["plugins/_shared/foo.py"],
		"head_version": "0.4.39",
		"staged_version": "0.4.39",
		"lockfiles": {},
	}
	count(result) == 1
}

test_shared_change_bumped_lockfile_in_sync_passes if {
	result := shared_version_cascade.deny with input as {
		"shared_py_staged": ["plugins/_shared/foo.py"],
		"head_version": "0.4.39",
		"staged_version": "0.4.40",
		"lockfiles": {
			"uv.lock": "0.4.40",
			"plugins/_shared/uv.lock": "0.4.40",
		},
	}
	count(result) == 0
}

test_shared_change_bumped_lockfile_drift_denied if {
	result := shared_version_cascade.deny with input as {
		"shared_py_staged": ["plugins/_shared/foo.py"],
		"head_version": "0.4.39",
		"staged_version": "0.4.40",
		"lockfiles": {
			"uv.lock": "0.4.40",
			"plugins/_shared/uv.lock": "0.4.39",
		},
	}
	count(result) == 1
}
