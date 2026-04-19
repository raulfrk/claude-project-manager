from server.lib.group_tags import parent_id_from_tags, strip_group_tags


def test_extracts_parent_id_from_group_tag() -> None:
    assert parent_id_from_tags(["group:3"]) == "3"


def test_extracts_nested_parent_id() -> None:
    assert parent_id_from_tags(["group:3.2"]) == "3.2"


def test_returns_none_when_no_group_tag() -> None:
    assert parent_id_from_tags(["feature", "urgent"]) is None


def test_ignores_malformed_group_tag() -> None:
    assert parent_id_from_tags(["group:"]) is None


def test_returns_first_group_tag_when_multiple() -> None:
    # Defensive — multiple group tags shouldn't exist, but pick a deterministic one
    assert parent_id_from_tags(["group:3", "group:5"]) == "3"


def test_strip_group_tags_removes_group_entries() -> None:
    assert strip_group_tags(["feature", "group:3", "urgent"]) == ["feature", "urgent"]


def test_strip_group_tags_preserves_order() -> None:
    assert strip_group_tags(["a", "group:3", "b", "group:5", "c"]) == ["a", "b", "c"]


def test_strip_group_tags_handles_all_group() -> None:
    assert strip_group_tags(["group:1", "group:2"]) == []


def test_strip_group_tags_handles_no_group() -> None:
    assert strip_group_tags(["a", "b", "c"]) == ["a", "b", "c"]


def test_strip_group_tags_handles_empty() -> None:
    assert strip_group_tags([]) == []


def test_strip_group_tags_preserves_group_prefix_non_match() -> None:
    # Tags that merely contain "group" but not the prefix form stay intact.
    assert strip_group_tags(["grouping", "outgroup"]) == ["grouping", "outgroup"]
