"""Unit tests for ``drive_search`` and ``drive_get_metadata`` MCP tools
and their SDK helpers.

The Drive HTTP boundary is mocked; the SDK shape conversion and the
MCP wrapper layer run unaltered.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from gwsa import GoogleAccount, Profile
from gwsa.mcp.tools.drive import (
    drive_get_metadata,
    drive_search,
    drive_set_properties,
)
from gwsa.sdk import drive
from mcp_app.context import current_user
from mcp_app.models import UserRecord


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


# --- search_drive SDK shape conversion -------------------------------


def _files_list_response(files: list[dict], next_token: str | None = None) -> dict:
    body = {"files": files}
    if next_token:
        body["nextPageToken"] = next_token
    return body


def test_search_drive_returns_normalized_shape():
    """SDK reshapes Drive's raw ``files.list`` payload to the gwsa
    standard: snake_case keys, parents list, url field."""
    raw = _files_list_response([
        {
            "id": "f1",
            "name": "invoice.pdf",
            "mimeType": "application/pdf",
            "modifiedTime": "2026-05-10T00:00:00Z",
            "size": "12345",
            "parents": ["folder-a"],
            "webViewLink": "https://drive.google.com/file/d/f1/view",
        },
    ])
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.search.get_drive_service", return_value=fake_service
    ):
        result = drive.search_drive(query="name contains 'invoice'")
    assert result["items"] == [
        {
            "id": "f1",
            "name": "invoice.pdf",
            "mime_type": "application/pdf",
            "modified_time": "2026-05-10T00:00:00Z",
            "size": "12345",
            "parents": ["folder-a"],
            "url": "https://drive.google.com/file/d/f1/view",
        }
    ]
    assert result["next_page_token"] is None


def test_search_drive_expands_shortcut_target_fields():
    """Shortcut entries surface ``target_id`` and ``target_mime_type``
    so the agent can resolve to the real file."""
    raw = _files_list_response([
        {
            "id": "sc-1",
            "name": "shortcut-to-thing",
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {
                "targetId": "real-file-id",
                "targetMimeType": "application/pdf",
            },
        }
    ])
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.search.get_drive_service", return_value=fake_service
    ):
        result = drive.search_drive(query="x")
    item = result["items"][0]
    assert item["target_id"] == "real-file-id"
    assert item["target_mime_type"] == "application/pdf"


def test_search_drive_alldrives_corpora_adds_shared_drive_params():
    """``corpora="allDrives"`` triggers the Shared-Drive-aware flags
    the API requires when crossing drive boundaries."""
    raw = _files_list_response([])
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.search.get_drive_service", return_value=fake_service
    ):
        drive.search_drive(query="x", corpora="allDrives")
    call = fake_service.files.return_value.list.call_args.kwargs
    assert call["corpora"] == "allDrives"
    assert call["includeItemsFromAllDrives"] is True
    assert call["supportsAllDrives"] is True


def test_search_drive_default_corpora_user():
    raw = _files_list_response([])
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.search.get_drive_service", return_value=fake_service
    ):
        drive.search_drive(query="x")
    call = fake_service.files.return_value.list.call_args.kwargs
    assert call["corpora"] == "user"
    assert "includeItemsFromAllDrives" not in call


def test_search_drive_rejects_unknown_corpora():
    with pytest.raises(ValueError, match="Unknown corpora"):
        drive.search_drive(query="x", corpora="not-a-real-corpora")


def test_search_drive_paginates_next_token():
    raw = _files_list_response([], next_token="next-page-token-abc")
    fake_service = MagicMock()
    fake_service.files.return_value.list.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.search.get_drive_service", return_value=fake_service
    ):
        result = drive.search_drive(query="x")
    assert result["next_page_token"] == "next-page-token-abc"


# --- get_metadata SDK helper -----------------------------------------


def test_get_metadata_returns_normalized_shape():
    raw = {
        "id": "f1",
        "name": "report.pdf",
        "mimeType": "application/pdf",
        "size": "98765",
        "parents": ["folder-x"],
        "modifiedTime": "2026-05-10T00:00:00Z",
        "webViewLink": "https://drive.google.com/file/d/f1/view",
        "trashed": False,
    }
    fake_service = MagicMock()
    fake_service.files.return_value.get.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.files.get_drive_service", return_value=fake_service
    ):
        result = drive.get_metadata(file_id="f1")
    assert result == {
        "id": "f1",
        "name": "report.pdf",
        "mime_type": "application/pdf",
        "size": "98765",
        "parents": ["folder-x"],
        "modified_time": "2026-05-10T00:00:00Z",
        "url": "https://drive.google.com/file/d/f1/view",
        "trashed": False,
    }


def test_get_metadata_handles_shortcut():
    raw = {
        "id": "sc-1",
        "name": "shortcut",
        "mimeType": "application/vnd.google-apps.shortcut",
        "shortcutDetails": {
            "targetId": "real-file",
            "targetMimeType": "application/pdf",
        },
    }
    fake_service = MagicMock()
    fake_service.files.return_value.get.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.files.get_drive_service", return_value=fake_service
    ):
        result = drive.get_metadata(file_id="sc-1")
    assert result["target_id"] == "real-file"
    assert result["target_mime_type"] == "application/pdf"


def test_get_metadata_handles_native_google_file_missing_size():
    """Native Google Workspace formats (Docs/Sheets/Slides) have no raw
    byte count — the API simply omits the field."""
    raw = {
        "id": "doc-1",
        "name": "My Doc",
        "mimeType": "application/vnd.google-apps.document",
        # no size field
        "modifiedTime": "2026-05-10T00:00:00Z",
        "trashed": False,
    }
    fake_service = MagicMock()
    fake_service.files.return_value.get.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.files.get_drive_service", return_value=fake_service
    ):
        result = drive.get_metadata(file_id="doc-1")
    assert result["size"] is None
    assert result["mime_type"] == "application/vnd.google-apps.document"


def test_get_metadata_uses_supports_all_drives_flag():
    raw = {"id": "f1", "name": "x", "mimeType": "text/plain"}
    fake_service = MagicMock()
    fake_service.files.return_value.get.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.files.get_drive_service", return_value=fake_service
    ):
        drive.get_metadata(file_id="f1")
    call = fake_service.files.return_value.get.call_args.kwargs
    assert call["supportsAllDrives"] is True


# --- drive_search MCP tool -------------------------------------------


def test_drive_search_mcp_tool_delegates_to_sdk():
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "items": [
                {
                    "id": "f1",
                    "name": "x.pdf",
                    "mime_type": "application/pdf",
                    "size": "100",
                    "parents": ["root"],
                    "url": "u",
                    "modified_time": "t",
                }
            ],
            "next_page_token": None,
        }
        with patch(
            "gwsa.sdk.drive.search_drive", return_value=sdk_response
        ) as patched:
            result = asyncio.run(
                drive_search(
                    query="name contains 'x'",
                    max_results=10,
                    corpora="allDrives",
                )
            )
        patched.assert_called_once_with(
            query="name contains 'x'",
            max_results=10,
            corpora="allDrives",
            account=None,
        )
        assert result == sdk_response
    finally:
        current_user.reset(tok)


def test_drive_search_mcp_returns_error_envelope_on_bad_corpora():
    """ValueError from invalid corpora becomes a structured error
    envelope, not a thrown exception."""
    tok = _set_user_with_account()
    try:
        with patch(
            "gwsa.sdk.drive.search_drive",
            side_effect=ValueError("Unknown corpora value: 'bogus'."),
        ):
            result = asyncio.run(drive_search(query="x", corpora="bogus"))
        assert "error" in result
        assert "bogus" in result["error"]
    finally:
        current_user.reset(tok)


def test_drive_search_mcp_returns_error_envelope_on_api_failure():
    tok = _set_user_with_account()
    try:
        with patch(
            "gwsa.sdk.drive.search_drive",
            side_effect=RuntimeError("Drive API quota exceeded"),
        ):
            result = asyncio.run(drive_search(query="x"))
        assert "error" in result
        assert "quota" in result["error"]
    finally:
        current_user.reset(tok)


# --- drive_get_metadata MCP tool -------------------------------------


def test_drive_get_metadata_mcp_happy_path():
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "id": "f1",
            "name": "x.pdf",
            "mime_type": "application/pdf",
            "size": "1234",
            "parents": ["folder-a"],
            "modified_time": "2026-05-10T00:00:00Z",
            "url": "https://drive.google.com/file/d/f1/view",
            "trashed": False,
        }
        with patch(
            "gwsa.sdk.drive.get_metadata", return_value=sdk_response
        ) as patched:
            result = asyncio.run(drive_get_metadata(file_id="f1"))
        patched.assert_called_once_with(file_id="f1", account=None)
        assert result == sdk_response
    finally:
        current_user.reset(tok)


def test_drive_get_metadata_mcp_returns_error_envelope_on_failure():
    tok = _set_user_with_account()
    try:
        with patch(
            "gwsa.sdk.drive.get_metadata",
            side_effect=RuntimeError("File not found: bogus-id"),
        ):
            result = asyncio.run(drive_get_metadata(file_id="bogus-id"))
        assert "error" in result
        assert "bogus-id" in result["error"]
    finally:
        current_user.reset(tok)


# --- set_properties SDK ----------------------------------------------


def test_set_properties_sends_merge_body_single_call():
    raw = {
        "id": "f1",
        "name": "Test File",
        "properties": {"myapp": "expense-tracker"},
    }
    fake_service = MagicMock()
    fake_service.files.return_value.update.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.files.get_drive_service", return_value=fake_service
    ):
        result = drive.set_properties(
            file_id="f1",
            properties={"myapp": "expense-tracker"},
        )
    # One update call, no prior get (merge is server-side).
    fake_service.files.return_value.get.assert_not_called()
    call = fake_service.files.return_value.update.call_args.kwargs
    assert call["fileId"] == "f1"
    assert call["body"] == {"properties": {"myapp": "expense-tracker"}}
    assert call["supportsAllDrives"] is True
    assert result["properties"] == {"myapp": "expense-tracker"}
    assert result["app_properties"] == {}


def test_set_properties_null_value_deletes_key():
    raw = {"id": "f1", "name": "x", "properties": {}}
    fake_service = MagicMock()
    fake_service.files.return_value.update.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.files.get_drive_service", return_value=fake_service
    ):
        drive.set_properties(file_id="f1", properties={"stale": None})
    body = fake_service.files.return_value.update.call_args.kwargs["body"]
    assert body == {"properties": {"stale": None}}


def test_set_properties_supports_app_properties():
    raw = {"id": "f1", "name": "x", "appProperties": {"k": "v"}}
    fake_service = MagicMock()
    fake_service.files.return_value.update.return_value.execute.return_value = raw
    with patch(
        "gwsa.sdk.drive.files.get_drive_service", return_value=fake_service
    ):
        result = drive.set_properties(file_id="f1", app_properties={"k": "v"})
    body = fake_service.files.return_value.update.call_args.kwargs["body"]
    assert body == {"appProperties": {"k": "v"}}
    assert result["app_properties"] == {"k": "v"}


def test_set_properties_requires_at_least_one_map():
    with pytest.raises(ValueError):
        drive.set_properties(file_id="f1")


# --- set_properties MCP tool -----------------------------------------


def test_drive_set_properties_mcp_happy_path():
    tok = _set_user_with_account()
    try:
        sdk_response = {
            "id": "f1",
            "name": "Test File",
            "properties": {"myapp": "expense-tracker"},
            "app_properties": {},
        }
        with patch(
            "gwsa.sdk.drive.set_properties", return_value=sdk_response
        ) as patched:
            result = asyncio.run(
                drive_set_properties(
                    file_id="f1",
                    properties={"myapp": "expense-tracker"},
                )
            )
        patched.assert_called_once_with(
            "f1",
            properties={"myapp": "expense-tracker"},
            app_properties=None,
            account=None,
        )
        assert result == sdk_response
    finally:
        current_user.reset(tok)


def test_drive_set_properties_mcp_missing_maps_returns_error():
    tok = _set_user_with_account()
    try:
        result = asyncio.run(drive_set_properties(file_id="f1"))
        assert "error" in result
    finally:
        current_user.reset(tok)
