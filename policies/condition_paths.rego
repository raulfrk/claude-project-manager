package cpm.condition_paths

import rego.v1

# Input is a plugin's default-hooks.yaml.
# Asserts: every atomic path in any hook's `condition` string is in valid_paths.

valid_paths := {
	"sandbox_integration",
	"zoxide_integration",
	"git_tracking.enabled",
	"sync.todoist.enabled",
	"sync.todoist.auto_sync",
	"todo.todoist_task_id",
	"project.todoist_project_id",
	"sync.trello.enabled",
	"sync.trello.auto_sync",
	"sync.trello.list_mappings.archived",
	"project.trello_card_id",
	"todo.trello_card_id",
	"sync.jira.enabled",
	"sync.jira.auto_sync",
	"project.jira_issue_key",
	"todo.jira_issue_key",
	"sync.wiki.enabled",
	"sync.wiki.auto_sync",
	"sync.wiki.auto_ingest_sessions",
	"sync.wiki.capture_notes_as_log",
	"sync.wiki.replace_notes_md",
	"sync.confluence.enabled",
}

deny contains msg if {
	some hook in input.hooks
	cond := hook.condition
	paths := atomic_paths(cond)
	some path in paths
	not path in valid_paths
	msg := sprintf("unknown condition path %q in hook %q", [path, hook.id])
}

# Splits cond on `and`/`or` operators and strips leading `!` negation.
atomic_paths(cond) := paths if {
	s := replace(cond, " and ", "|")
	t := replace(s, " or ", "|")
	raw := split(t, "|")
	paths := {trim_left(trim_space(p), "!") | some p in raw}
}
