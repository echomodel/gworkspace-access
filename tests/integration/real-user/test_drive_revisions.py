"""Integration tests for Drive file revisions.

Self-contained: uploads a scratch file, updates it to mint a second
revision, then exercises the full version-store round-trip — list,
fetch an old revision's content, pin/unpin — and cleans up. Proves the
core promise of issue #38: a past revision's bytes are retrievable for
an uploaded (non-native) file.
"""

from __future__ import annotations

import time

import pytest

from gwsa.sdk import drive


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}.json"


def _safe_trash(file_id: str) -> None:
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


@pytest.mark.integration
def test_revision_roundtrip_list_fetch_keep_unkeep():
    v1 = b'{"version": 1, "note": "original"}'
    v2 = b'{"version": 2, "note": "updated"}'
    name = _unique_name("revisions-roundtrip")

    uploaded = drive.upload_bytes(data=v1, name=name, mime_type="application/json")
    file_id = uploaded.get("id")
    assert file_id, f"upload_bytes returned no id: {uploaded}"

    try:
        # Mint a second revision.
        drive.update_bytes(
            file_id=file_id, data=v2, mime_type="application/json"
        )

        # List — expect at least two revisions, oldest first.
        listing = drive.list_revisions(file_id=file_id)
        items = listing["items"]
        assert len(items) >= 2, f"expected >=2 revisions, got {len(items)}"
        oldest = items[0]

        # Fetch the oldest revision's content — must equal v1 byte-for-byte.
        fetched = drive.download_revision_bytes(
            file_id=file_id, revision_id=oldest["id"]
        )
        assert fetched["data"] == v1
        assert fetched["revision_id"] == oldest["id"]

        # Pin the oldest (non-head) revision.
        pinned = drive.keep_revision(file_id=file_id, revision_id=oldest["id"])
        assert pinned["keep_forever"] is True

        # Drive asymmetry: a pinned NON-HEAD revision cannot be unpinned.
        with pytest.raises(drive.KeepForeverUnsetError):
            drive.unkeep_revision(file_id=file_id, revision_id=oldest["id"])

        # The HEAD revision, by contrast, toggles both ways.
        head = items[-1]
        assert drive.keep_revision(
            file_id=file_id, revision_id=head["id"]
        )["keep_forever"] is True
        assert drive.unkeep_revision(
            file_id=file_id, revision_id=head["id"]
        )["keep_forever"] is False
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_update_with_keep_pins_resulting_revision():
    """`keep_revision_forever=True` on update pins the new head revision
    in one call — no separate keep_revision needed."""
    name = _unique_name("revisions-keepflag")
    up = drive.upload_bytes(
        data=b'{"v": 1}', name=name, mime_type="application/json"
    )
    file_id = up.get("id")
    assert file_id

    try:
        drive.update_bytes(
            file_id=file_id,
            data=b'{"v": 2}',
            mime_type="application/json",
            keep_revision_forever=True,
        )
        items = drive.list_revisions(file_id=file_id)["items"]
        head = items[-1]
        assert head["keep_forever"] is True, (
            "update --keep should have pinned the new head revision"
        )
    finally:
        _safe_trash(file_id)
