from server.lib.group_tags import parent_id_from_tags


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
