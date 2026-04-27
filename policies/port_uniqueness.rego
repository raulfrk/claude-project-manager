package cpm.port_uniqueness

import rego.v1

# Input is plugins/_shared/ports.yaml (a {plugin: port} map).
# Asserts: no two plugins share the same port value.

deny contains msg if {
	# Cross-product over object keys; lex compare avoids reporting the same
	# pair twice (e.g. (a,b) and (b,a)). is_number scopes the rule to
	# port-mapping inputs only, so the policy is safe to run --all-namespaces
	# against unrelated JSON/YAML inputs (e.g. the shared_version_cascade
	# state JSON, which has string values).
	some plugin1
	some plugin2
	is_number(input[plugin1])
	is_number(input[plugin2])
	plugin1 < plugin2
	input[plugin1] == input[plugin2]
	msg := sprintf(
		"ports collide: %s and %s both use %v",
		[plugin1, plugin2, input[plugin1]],
	)
}
