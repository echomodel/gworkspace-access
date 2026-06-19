"""Integration tests for custom Drive properties (set + discover).

Self-contained: creates a scratch file, tags it, finds it by the tag
via ``search_drive``, mutates/deletes a key, and trashes the file.

Covers:
- ``drive.set_properties`` — merge semantics, null-deletes, single call
- discovery via ``drive.search_drive`` with a ``properties has {...}``
  query (the pattern skills use to resolve a backing file by tag)
"""

from __future__ import annotations

import time

import pytest

from gwsa.sdk import drive


def _unique(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _safe_trash(file_id: str) -> None:
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


@pytest.mark.integration
def test_set_properties_tag_and_discover_by_query():
    name = _unique("gwsa-it-props") + ".txt"
    uploaded = drive.upload_bytes(
        data=b"property discovery test\n",
        name=name,
        mime_type="text/plain",
    )
    file_id = uploaded.get("id")
    assert file_id, f"upload_bytes returned no id: {uploaded}"
    # A value unique to this run so the discovery query matches exactly one.
    tag_value = _unique("expense-tracker")
    try:
        # Tag it (public properties, namespaced key).
        res = drive.set_properties(
            file_id,
            properties={"myapp": tag_value, "myapp_role": "primary"},
        )
        assert res["properties"]["myapp"] == tag_value
        assert res["properties"]["myapp_role"] == "primary"

        # Discover by the tag — the skill's resolve-by-property pattern.
        found = drive.search_drive(
            query=(
                "properties has { key='myapp' "
                f"and value='{tag_value}' }}"
            ),
        )
        ids = [f["id"] for f in found.get("items", [])]
        assert file_id in ids, f"tag query did not find the file: {found}"

        # Merge: add a key, leave others untouched.
        drive.set_properties(file_id, properties={"myapp_extra": "x"})
        # Delete a key via null; others remain.
        after = drive.set_properties(
            file_id, properties={"myapp_role": None}
        )
        props = after["properties"]
        assert "myapp_role" not in props
        assert props.get("myapp") == tag_value
        assert props.get("myapp_extra") == "x"
    finally:
        _safe_trash(file_id)
