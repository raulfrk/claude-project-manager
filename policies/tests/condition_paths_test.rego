package cpm.condition_paths_test

import data.cpm.condition_paths
import rego.v1

test_known_path_passes if {
	result := condition_paths.deny with input as {"hooks": [{
		"id": "h1",
		"condition": "git_tracking.enabled",
	}]}
	count(result) == 0
}

test_unknown_path_detected if {
	result := condition_paths.deny with input as {"hooks": [{
		"id": "h1",
		"condition": "git_tracking.enabledd",
	}]}
	count(result) == 1
}

test_compound_condition_passes if {
	result := condition_paths.deny with input as {"hooks": [{
		"id": "h1",
		"condition": "sync.todoist.enabled and sync.todoist.auto_sync",
	}]}
	count(result) == 0
}

test_negation_handled if {
	result := condition_paths.deny with input as {"hooks": [{
		"id": "h1",
		"condition": "!git_tracking.enabled",
	}]}
	count(result) == 0
}

test_compound_with_unknown_partial_detected if {
	result := condition_paths.deny with input as {"hooks": [{
		"id": "h1",
		"condition": "git_tracking.enabled and unknown.path",
	}]}
	count(result) == 1
}

test_empty_condition_skipped if {
	result := condition_paths.deny with input as {"hooks": [{
		"id": "h1",
		"condition": "",
	}]}
	count(result) == 0
}

test_whitespace_only_condition_skipped if {
	result := condition_paths.deny with input as {"hooks": [{
		"id": "h1",
		"condition": "   ",
	}]}
	count(result) == 0
}
