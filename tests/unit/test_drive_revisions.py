"""Unit tests for the Drive revisions SDK + MCP surface.

Sociable style: the only mocked boundary is the Drive API service
(`get_drive_service`); the SDK reshaping logic and the MCP tool's
error-envelope handling run unaltered. Byte-roundtrip retrievability
is proven in the integration suite (it needs the real `alt=media`
download path); here we cover shape normalization, the keepForever
toggle, and the native-file guard.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError

from gwsa.sdk import drive
from gwsa.sdk.drive.revisions import (
    KeepForeverUnsetError,
    NativeFileRevisionError,
)


def _fake_service():
    return MagicMock()


def test_list_revisions_normalizes_shape():
    raw = {
        "revisions": [
            {
                "id": "1",
                "modifiedTime": "2026-05-01T00:00:00Z",
                "keepForever": False,
                "size": "120",
                "md5Checksum": "abc123",
                "mimeType": "application/json",
                "originalFilename": "data.json",
                "lastModifyingUser": {
                    "displayName": "Test User",
                    "emailAddress": "user@example.com",
                },
            },
            {
                "id": "2",
                "modifiedTime": "2026-05-02T00:00:00Z",
                "keepForever": True,
                "size": "131",
                "md5Checksum": "def456",
                "mimeType": "application/json",
                "originalFilename": "data.json",
                "lastModifyingUser": {"displayName": "Test User"},
            },
        ]
        # no nextPageToken → single page
    }
    svc = _fake_service()
    svc.revisions.return_value.list.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = drive.list_revisions(file_id="file-1")

    assert result["file_id"] == "file-1"
    assert result["items"] == [
        {
            "id": "1",
            "modified_time": "2026-05-01T00:00:00Z",
            "keep_forever": False,
            "size": "120",
            "md5_checksum": "abc123",
            "mime_type": "application/json",
            "original_filename": "data.json",
            "last_modifying_user": "Test User",
        },
        {
            "id": "2",
            "modified_time": "2026-05-02T00:00:00Z",
            "keep_forever": True,
            "size": "131",
            "md5_checksum": "def456",
            "mime_type": "application/json",
            "original_filename": "data.json",
            "last_modifying_user": "Test User",
        },
    ]


def test_match_revision_finds_matching_md5():
    import hashlib
    content = b'{"v": 1}'
    md5 = hashlib.md5(content).hexdigest()
    svc = _fake_service()
    svc.revisions.return_value.list.return_value.execute.return_value = {
        "revisions": [
            {"id": "old", "md5Checksum": "deadbeef", "keepForever": False},
            {"id": "hit", "md5Checksum": md5, "keepForever": False,
             "modifiedTime": "2026-05-02T00:00:00Z", "size": "8"},
        ]
    }
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = drive.match_revision_bytes("f", content)
    assert result["matched"] is True
    assert result["revision"]["id"] == "hit"
    assert result["md5"] == md5
    assert result["pinned"] is False


def test_match_revision_no_match():
    svc = _fake_service()
    svc.revisions.return_value.list.return_value.execute.return_value = {
        "revisions": [
            {"id": "r1", "md5Checksum": "deadbeef", "keepForever": False},
        ]
    }
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = drive.match_revision_bytes("f", b"content-not-present")
    assert result["matched"] is False
    assert result["revision"] is None


def test_match_revision_pin_flips_keep_forever():
    import hashlib
    content = b'{"v": 1}'
    md5 = hashlib.md5(content).hexdigest()
    svc = _fake_service()
    svc.revisions.return_value.list.return_value.execute.return_value = {
        "revisions": [
            {"id": "hit", "md5Checksum": md5, "keepForever": False},
        ]
    }
    svc.revisions.return_value.update.return_value.execute.return_value = {
        "id": "hit", "keepForever": True,
    }
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = drive.match_revision_bytes("f", content, pin=True)
    assert result["matched"] is True
    assert result["pinned"] is True
    assert result["revision"]["keep_forever"] is True
    # the pin went through revisions.update with keepForever true
    _, kwargs = svc.revisions.return_value.update.call_args
    assert kwargs["body"] == {"keepForever": True}


def test_match_revision_native_file_no_checksum():
    svc = _fake_service()
    svc.revisions.return_value.list.return_value.execute.return_value = {
        "revisions": [
            {"id": "r1", "mimeType": "application/vnd.google-apps.document"},
        ]
    }
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = drive.match_revision_bytes("f", b"anything")
    assert result["matched"] is False
    assert "note" in result


def test_keep_revision_sets_keepforever_true():
    svc = _fake_service()
    svc.revisions.return_value.update.return_value.execute.return_value = {
        "id": "2",
        "keepForever": True,
        "mimeType": "application/json",
    }
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = drive.keep_revision(file_id="file-1", revision_id="2")

    # body carried keepForever=true
    _, kwargs = svc.revisions.return_value.update.call_args
    assert kwargs["body"] == {"keepForever": True}
    assert kwargs["fileId"] == "file-1"
    assert kwargs["revisionId"] == "2"
    assert result["keep_forever"] is True


def test_unkeep_revision_sets_keepforever_false():
    svc = _fake_service()
    svc.revisions.return_value.update.return_value.execute.return_value = {
        "id": "2",
        "keepForever": False,
        "mimeType": "application/json",
    }
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = drive.unkeep_revision(file_id="file-1", revision_id="2")

    _, kwargs = svc.revisions.return_value.update.call_args
    assert kwargs["body"] == {"keepForever": False}
    assert result["keep_forever"] is False


def test_unkeep_nonhead_revision_raises_typed_error():
    """Drive rejects unpinning a pinned non-head revision with
    ``illegalKeepForeverModification``; the SDK translates that raw
    HttpError into the typed KeepForeverUnsetError. (Verified against the
    live API — see the integration suite.)"""
    content = (
        b'{"error": {"code": 400, '
        b'"message": "Cannot update a revision to false that is marked '
        b'as keepForever.", "errors": [{"message": "Cannot update.", '
        b'"domain": "global", "reason": "illegalKeepForeverModification"}]}}'
    )
    resp = MagicMock()
    resp.status = 400
    resp.reason = "Bad Request"
    http_error = HttpError(resp, content)
    # Precondition: our detection substring is present in the error text.
    assert "illegalKeepForeverModification" in str(http_error)

    svc = _fake_service()
    svc.revisions.return_value.update.return_value.execute.side_effect = (
        http_error
    )
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        try:
            drive.unkeep_revision(file_id="file-1", revision_id="1")
            assert False, "expected KeepForeverUnsetError"
        except KeepForeverUnsetError as e:
            assert e.revision_id == "1"


def test_upload_bytes_forwards_keep_revision_forever():
    """The --keep / keep_revision_forever path pins atomically via the
    files.create keepRevisionForever query param."""
    svc = _fake_service()
    svc.files.return_value.create.return_value.execute.return_value = {
        "id": "f", "name": "n.json", "webViewLink": "u",
    }
    with patch(
        "gwsa.sdk.drive.upload.get_drive_service", return_value=svc
    ):
        result = drive.upload_bytes(
            data=b"x", name="n.json", mime_type="application/json",
            keep_revision_forever=True,
        )
    _, kwargs = svc.files.return_value.create.call_args
    assert kwargs["keepRevisionForever"] is True
    assert result["keep_revision_forever"] is True


def test_update_bytes_forwards_keep_revision_forever():
    svc = _fake_service()
    svc.files.return_value.update.return_value.execute.return_value = {
        "id": "f", "name": "n.json", "webViewLink": "u",
    }
    with patch(
        "gwsa.sdk.drive.upload.get_drive_service", return_value=svc
    ):
        result = drive.update_bytes(
            file_id="f", data=b"x", mime_type="application/json",
            keep_revision_forever=True,
        )
    _, kwargs = svc.files.return_value.update.call_args
    assert kwargs["keepRevisionForever"] is True
    assert result["keep_revision_forever"] is True


def test_download_revision_bytes_rejects_native_file():
    """Native Google files have no exportable historical content; the
    SDK raises before attempting an alt=media download."""
    svc = _fake_service()
    svc.revisions.return_value.get.return_value.execute.return_value = {
        "id": "5",
        "mimeType": "application/vnd.google-apps.document",
    }
    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        try:
            drive.download_revision_bytes(file_id="doc-1", revision_id="5")
            assert False, "expected NativeFileRevisionError"
        except NativeFileRevisionError as e:
            assert e.mime_type == "application/vnd.google-apps.document"
        # get_media must never be called for a native file
        svc.revisions.return_value.get_media.assert_not_called()


def test_mcp_get_revision_returns_native_envelope():
    """The MCP tool surfaces the native-file limitation as a structured
    envelope rather than raising."""
    svc = _fake_service()
    svc.revisions.return_value.get.return_value.execute.return_value = {
        "id": "5",
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    from gwsa.mcp.tools.drive import drive_get_revision

    with patch(
        "gwsa.sdk.drive.revisions.get_drive_service", return_value=svc
    ):
        result = asyncio.run(
            drive_get_revision(file_id="sheet-1", revision_id="5")
        )

    assert isinstance(result, dict)
    assert result["native_file"] is True
    assert result["success"] is False
    assert "spreadsheet" in result["mime_type"]
