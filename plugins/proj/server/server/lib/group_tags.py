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
