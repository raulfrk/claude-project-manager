"""Flat-model group-tag helpers: ``group:<parent_id>`` tags encode parent membership."""

from __future__ import annotations

_GROUP_PREFIX = "group:"


def parent_id_from_tags(tags: list[str]) -> str | None:
    """Return the parent id encoded in the first ``group:<id>`` tag, or None.

    The flat model stores parent membership on children as ``group:<parent.id>``.
    Returns None when no group tag is present or the tag has an empty id.
    """
    for tag in tags:
        if tag.startswith(_GROUP_PREFIX):
            pid = tag[len(_GROUP_PREFIX) :]
            if pid:
                return pid
    return None


def strip_group_tags(tags: list[str]) -> list[str]:
    """Return ``tags`` without any ``group:*`` entries.

    Use when surfacing tags to an external integration (Todoist labels, Trello
    labels, Jira labels) — ``group:<parent_id>`` is internal flat-model state
    and must not leak into third-party sync targets per 624 contract.
    """
    return [t for t in tags if not t.startswith(_GROUP_PREFIX)]
