package cpm.port_uniqueness_test

import data.cpm.port_uniqueness
import rego.v1

test_unique_passes if {
	result := port_uniqueness.deny with input as {
		"router": 19100,
		"proj": 19102,
		"wiki": 19109,
	}
	count(result) == 0
}

test_collision_detected if {
	result := port_uniqueness.deny with input as {
		"proj": 19102,
		"wiki": 19102,
	}
	count(result) == 1
}

test_no_double_report if {
	# Three colliding plugins should produce 3 unique pair messages, not 6.
	result := port_uniqueness.deny with input as {
		"a": 19100,
		"b": 19100,
		"c": 19100,
	}
	count(result) == 3
}
