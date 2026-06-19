"""Tests for the byte-producing MCP tools refactored in #30 / #31.

Covers:
- ``download_email_attachment`` with inline and drive destinations
- ``drive_download`` (inline-only)
- ``drive_move`` and ``drive_delete`` (new primitives)

The Gmail / Drive HTTP calls are mocked at the SDK boundary; the
MCP tool layer and the destination materialize() helper run unaltered.
"""

from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import patch

from mcp.types import EmbeddedResource, TextContent
from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile
from gwsa.mcp.tools.drive import (
    drive_delete,
    drive_download,
    drive_download_to_path,
    drive_move,
)
from gwsa.mcp.tools.mail import download_email_attachment
from gwsa.sdk.destinations import (
    DEFAULT_INLINE_SIZE_CAP_BYTES,
    DriveDestination,
    InlineDestination,
)


def _set_user_with_account():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token={
                    "client_id": "user-owned-client",
                    "client_secret": "test-secret",
                    "refresh_token": "test-refresh",
                    "token_uri": "https://oauth2.googleapis.com/token",
                },
            ),
        ],
    )
    user = UserRecord(
        email="alice@example.com",
        profile=profile.model_dump(mode="json"),
    )
    return current_user.set(user)


# --- download_email_attachment ---------------------------------------


def test_attachment_inline_returns_content_blocks():
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "data": b"hello pdf",
            "size": 9,
            "filename": "report.pdf",
            "mime_type": "application/pdf",
        }
        with patch(
            "gwsa.sdk.mail.get_attachment_with_metadata",
            return_value=sdk_response,
        ):
            blocks = asyncio.run(
                download_email_attachment(
                    message_id="msg-1",
                    attachment_id="att-1",
                    destination=InlineDestination(),
                )
            )
        assert isinstance(blocks, list)
        assert len(blocks) == 2
        summary, embedded = blocks
        assert isinstance(summary, TextContent)
        summary_data = json.loads(summary.text)
        assert summary_data["destination"] == "inline"
        assert summary_data["name"] == "report.pdf"
        assert summary_data["size_bytes"] == 9
        assert summary_data["mime_type"] == "application/pdf"
        assert isinstance(embedded, EmbeddedResource)
        assert embedded.resource.mimeType == "application/pdf"
        decoded = base64.b64decode(embedded.resource.blob)
        assert decoded == b"hello pdf"
    finally:
        current_user.reset(tok)


def test_attachment_drive_destination_uploads_and_returns_dict():
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "data": b"payload",
            "size": 7,
            "filename": "spreadsheet.xlsx",
            "mime_type": (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        }
        fake_upload = {
            "id": "uploaded-1",
            "name": "spreadsheet.xlsx",
            "url": "https://drive.google.com/file/d/uploaded-1/view",
        }
        with (
            patch(
                "gwsa.sdk.mail.get_attachment_with_metadata",
                return_value=sdk_response,
            ),
            patch(
                "gwsa.sdk.drive.upload_bytes",
                return_value=fake_upload,
            ) as upload_patch,
        ):
            result = asyncio.run(
                download_email_attachment(
                    message_id="msg-1",
                    attachment_id="att-1",
                    destination=DriveDestination(folder_id="proj-folder"),
                )
            )
        upload_patch.assert_called_once()
        assert upload_patch.call_args.kwargs["folder_id"] == "proj-folder"
        assert result["destination"] == "drive"
        assert result["drive_file_id"] == "uploaded-1"
        assert result["drive_url"] == fake_upload["url"]
        assert result["folder_id"] == "proj-folder"
        assert result["size_bytes"] == 7
    finally:
        current_user.reset(tok)


def test_attachment_inline_too_large_returns_error_envelope():
    tok = _set_user_with_account()
    try:
        oversize = b"x" * (DEFAULT_INLINE_SIZE_CAP_BYTES + 1)
        sdk_response = {
            "data": oversize,
            "size": len(oversize),
            "filename": "big.bin",
            "mime_type": "application/octet-stream",
        }
        with patch(
            "gwsa.sdk.mail.get_attachment_with_metadata",
            return_value=sdk_response,
        ):
            result = asyncio.run(
                download_email_attachment(
                    message_id="msg-1",
                    attachment_id="att-1",
                    destination=InlineDestination(),
                )
            )
        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["size_bytes"] == len(oversize)
        assert result["cap_bytes"] == DEFAULT_INLINE_SIZE_CAP_BYTES
        assert result["retry_with"] == {"kind": "drive"}
    finally:
        current_user.reset(tok)


def test_attachment_with_explicit_filename_skips_metadata_lookup():
    """When the caller passes filename + mime_type (from read_email),
    the tool uses them directly and never calls
    ``get_attachment_with_metadata`` — which is unreliable because
    Gmail rotates attachment IDs across messages.get calls."""
    tok = _set_user_with_account()
    try:
        bytes_only = {"data": b"PDFCONTENT", "size": 10}
        with (
            patch(
                "gwsa.sdk.mail.get_attachment",
                return_value=bytes_only,
            ) as bytes_patch,
            patch(
                "gwsa.sdk.mail.get_attachment_with_metadata",
            ) as meta_patch,
        ):
            blocks = asyncio.run(
                download_email_attachment(
                    message_id="msg-1",
                    attachment_id="att-1",
                    destination=InlineDestination(),
                    filename="Invoice.pdf",
                    mime_type="application/pdf",
                )
            )
        # Should have used the fast path — no metadata lookup at all.
        bytes_patch.assert_called_once()
        meta_patch.assert_not_called()
        summary, _embedded = blocks
        summary_data = json.loads(summary.text)
        assert summary_data["name"] == "Invoice.pdf"
        assert summary_data["mime_type"] == "application/pdf"
    finally:
        current_user.reset(tok)


def test_attachment_with_partial_metadata_falls_back_to_lookup():
    """If only one of filename/mime_type is provided, the tool falls
    back to the metadata lookup to recover the missing piece. The
    explicit value still wins."""
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "data": b"x",
            "size": 1,
            "filename": "from-lookup.bin",
            "mime_type": "application/octet-stream",
        }
        with patch(
            "gwsa.sdk.mail.get_attachment_with_metadata",
            return_value=sdk_response,
        ):
            blocks = asyncio.run(
                download_email_attachment(
                    message_id="msg-1",
                    attachment_id="att-1",
                    destination=InlineDestination(),
                    filename="Override.pdf",
                    # mime_type omitted → falls back to lookup
                )
            )
        summary, _embedded = blocks
        summary_data = json.loads(summary.text)
        # Explicit filename wins
        assert summary_data["name"] == "Override.pdf"
        # Mime recovered from lookup
        assert summary_data["mime_type"] == "application/octet-stream"
    finally:
        current_user.reset(tok)


def test_attachment_default_destination_is_drive():
    """When the caller omits ``destination`` entirely, gwsa defaults to
    Drive — the hosted-safe choice."""
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "data": b"hi",
            "size": 2,
            "filename": "note.txt",
            "mime_type": "text/plain",
        }
        fake_upload = {
            "id": "uploaded-2",
            "name": "note.txt",
            "url": "https://drive.google.com/file/d/uploaded-2/view",
        }
        with (
            patch(
                "gwsa.sdk.mail.get_attachment_with_metadata",
                return_value=sdk_response,
            ),
            patch(
                "gwsa.sdk.drive.upload_bytes",
                return_value=fake_upload,
            ),
        ):
            result = asyncio.run(
                download_email_attachment(
                    message_id="msg-1",
                    attachment_id="att-1",
                )
            )
        assert result["destination"] == "drive"
        assert result["folder_id"] is None  # My Drive root
    finally:
        current_user.reset(tok)


# --- drive_download (auto-select: inline small / Drive link large / save_to) ---


def test_drive_download_small_returns_inline_blocks():
    """A small file (size ≤ cap) comes back inline as content blocks."""
    tok = _set_user_with_account()
    try:
        meta = {"name": "memo.pdf", "mime_type": "application/pdf", "size": "10"}
        sdk_response = {
            "data": b"file bytes",
            "name": "memo.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 10,
        }
        with patch(
            "gwsa.sdk.drive.get_download_metadata", return_value=meta
        ), patch("gwsa.sdk.drive.download_bytes", return_value=sdk_response):
            blocks = asyncio.run(drive_download(file_id="drive-file-1"))
        assert isinstance(blocks, list)
        assert len(blocks) == 2
        summary, embedded = blocks
        assert isinstance(summary, TextContent)
        assert json.loads(summary.text)["name"] == "memo.pdf"
        assert isinstance(embedded, EmbeddedResource)
        assert base64.b64decode(embedded.resource.blob) == b"file bytes"
    finally:
        current_user.reset(tok)


def test_drive_download_large_returns_drive_link():
    """A large file returns the Drive download link (no proxy, no token)."""
    tok = _set_user_with_account()
    try:
        meta = {
            "name": "huge.bin",
            "mime_type": "application/octet-stream",
            "size": str(DEFAULT_INLINE_SIZE_CAP_BYTES + 1),
            "web_content_link": "https://drive.google.com/uc?id=X&export=download",
            "web_view_link": "https://drive.google.com/file/d/X/view",
        }
        with patch("gwsa.sdk.drive.get_download_metadata", return_value=meta):
            result = asyncio.run(drive_download(file_id="drive-file-1"))
        assert result["mode"] == "link"
        assert result["url"] == "https://drive.google.com/uc?id=X&export=download"
        assert result["name"] == "huge.bin"
    finally:
        current_user.reset(tok)


def test_drive_download_to_path_writes_locally(tmp_path):
    """drive_download_to_path (stdio only) writes the file to a local dir."""
    tok = _set_user_with_account()
    try:
        dest = str(tmp_path / "out.bin")
        saved = {"file_path": dest, "size": 1234, "name": "out.bin"}
        with patch("gwsa.sdk.drive.download_file", return_value=saved) as dl:
            result = asyncio.run(
                drive_download_to_path(file_id="drive-file-1", save_to=dest)
            )
        dl.assert_called_once()
        assert result["mode"] == "saved"
        assert result["path"] == dest
        assert result["size_bytes"] == 1234
    finally:
        current_user.reset(tok)


# --- drive_move / drive_delete ---------------------------------------


def test_drive_move_happy_path():
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "id": "drive-file-1",
            "name": "memo.pdf",
            "parents": ["new-folder-id"],
            "url": "https://drive.google.com/file/d/drive-file-1/view",
        }
        with patch(
            "gwsa.sdk.drive.move_file", return_value=sdk_response
        ) as move_patch:
            result = asyncio.run(
                drive_move(
                    file_id="drive-file-1",
                    destination_folder_id="new-folder-id",
                )
            )
        move_patch.assert_called_once_with(
            "drive-file-1",
            "new-folder-id",
            account=None,
        )
        assert result == sdk_response
    finally:
        current_user.reset(tok)


def test_drive_move_returns_error_envelope_on_failure():
    tok = _set_user_with_account()
    try:
        with patch(
            "gwsa.sdk.drive.move_file",
            side_effect=RuntimeError("File not found"),
        ):
            result = asyncio.run(
                drive_move(
                    file_id="missing",
                    destination_folder_id="folder-x",
                )
            )
        assert "error" in result
        assert "File not found" in result["error"]
    finally:
        current_user.reset(tok)


def test_drive_delete_happy_path():
    tok = _set_user_with_account()
    try:
        with patch(
            "gwsa.sdk.drive.delete_file",
            return_value={"file_id": "drive-file-1", "trashed": True},
        ) as delete_patch:
            result = asyncio.run(drive_delete(file_id="drive-file-1"))
        delete_patch.assert_called_once_with(
            file_id="drive-file-1", account=None
        )
        assert result == {"file_id": "drive-file-1", "trashed": True}
    finally:
        current_user.reset(tok)


def test_drive_delete_returns_error_envelope_on_failure():
    tok = _set_user_with_account()
    try:
        with patch(
            "gwsa.sdk.drive.delete_file",
            side_effect=RuntimeError("Permission denied"),
        ):
            result = asyncio.run(drive_delete(file_id="forbidden"))
        assert "error" in result
        assert "Permission denied" in result["error"]
    finally:
        current_user.reset(tok)
