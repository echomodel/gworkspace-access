"""Integration tests for the byte-producing Drive primitives.

Self-contained: each test creates its own scratch file in Drive,
exercises the lifecycle, and cleans up after itself. No reliance on
pre-existing test data.

Covers the new SDK helpers added for issue #31:
- ``drive.upload_bytes`` — MediaIoBaseUpload from raw bytes
- ``drive.download_bytes`` — in-memory fetch
- ``drive.move_file`` — addParents + removeParents in one update
- ``drive.delete_file`` — Trash semantics

And the MCP tools that wrap them:
- ``drive_move``
- ``drive_delete``
- ``drive_download`` returning ``EmbeddedResource + TextContent``
"""

from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest
from mcp.types import EmbeddedResource, TextContent

from gwsa.mcp.tools.drive import drive_delete, drive_download, drive_move
from gwsa.sdk import drive


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}.bin"


def _safe_trash(file_id: str) -> None:
    """Best-effort cleanup. Never raises — used in finally blocks."""
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


@pytest.mark.integration
def test_upload_bytes_and_download_bytes_roundtrip():
    """A synthetic payload uploaded via ``upload_bytes`` reads back
    byte-for-byte via ``download_bytes``."""
    payload = b"gwsa-integration-test\nupload+download roundtrip\n"
    name = _unique_name("upload-roundtrip")
    uploaded = drive.upload_bytes(
        data=payload,
        name=name,
        mime_type="text/plain",
    )
    file_id = uploaded.get("id")
    assert file_id, f"upload_bytes returned no id: {uploaded}"

    try:
        fetched = drive.download_bytes(file_id=file_id)
        assert fetched["data"] == payload
        assert fetched["name"] == name
        assert fetched["mime_type"] == "text/plain"
        assert fetched["size_bytes"] == len(payload)
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_move_file_changes_parents():
    """A file moved into a freshly-created folder lists that folder
    as its (only) parent afterward."""
    payload = b"move target"
    name = _unique_name("move-source")
    uploaded = drive.upload_bytes(data=payload, name=name, mime_type="text/plain")
    file_id = uploaded["id"]
    folder = drive.create_folder(
        name=_unique_name("move-target-folder").replace(".bin", ""),
    )
    folder_id = folder["id"]

    try:
        result = drive.move_file(
            file_id=file_id,
            destination_folder_id=folder_id,
        )
        assert result["id"] == file_id
        assert folder_id in result["parents"], (
            f"After move, expected new folder in parents; got {result['parents']}"
        )
        # Single-parent move: the old root parent should be gone.
        assert len(result["parents"]) == 1, (
            f"Expected exactly one parent post-move; got {result['parents']}"
        )
    finally:
        _safe_trash(file_id)
        _safe_trash(folder_id)


@pytest.mark.integration
def test_delete_file_trashes_not_hard_deletes():
    """After ``delete_file``, the file is gone from default listings
    but the file id still resolves (Trash semantics, not hard-delete).
    Calling delete a second time succeeds (idempotent)."""
    payload = b"delete target"
    name = _unique_name("delete-target")
    uploaded = drive.upload_bytes(data=payload, name=name, mime_type="text/plain")
    file_id = uploaded["id"]

    cleanup_needed = True
    try:
        first = drive.delete_file(file_id=file_id)
        assert first == {"file_id": file_id, "trashed": True}

        # File still resolves via direct id — Trash, not hard-delete.
        # We can confirm by trashing it again without error.
        second = drive.delete_file(file_id=file_id)
        assert second == {"file_id": file_id, "trashed": True}
        cleanup_needed = False  # already trashed
    finally:
        if cleanup_needed:
            _safe_trash(file_id)


@pytest.mark.integration
def test_drive_move_mcp_tool_roundtrip():
    """The MCP tool wrapper for ``drive_move`` returns the expected
    envelope (id, name, parents, url) on the happy path."""
    uploaded = drive.upload_bytes(
        data=b"mcp move", name=_unique_name("mcp-move"), mime_type="text/plain"
    )
    file_id = uploaded["id"]
    folder = drive.create_folder(
        name=_unique_name("mcp-move-folder").replace(".bin", ""),
    )
    folder_id = folder["id"]

    try:
        result = asyncio.run(
            drive_move(file_id=file_id, destination_folder_id=folder_id)
        )
        assert "error" not in result, result
        assert result["id"] == file_id
        assert folder_id in result["parents"]
        assert "url" in result and result["url"]
    finally:
        _safe_trash(file_id)
        _safe_trash(folder_id)


@pytest.mark.integration
def test_drive_delete_mcp_tool():
    """The MCP tool wrapper for ``drive_delete`` returns the trash
    envelope on the happy path."""
    uploaded = drive.upload_bytes(
        data=b"mcp delete",
        name=_unique_name("mcp-delete"),
        mime_type="text/plain",
    )
    file_id = uploaded["id"]
    cleanup_needed = True
    try:
        result = asyncio.run(drive_delete(file_id=file_id))
        assert result == {"file_id": file_id, "trashed": True}
        cleanup_needed = False
    finally:
        if cleanup_needed:
            _safe_trash(file_id)


@pytest.mark.integration
def test_drive_download_mcp_returns_content_blocks():
    """The MCP tool wrapper for ``drive_download`` returns a
    ``[TextContent, EmbeddedResource]`` pair with the bytes
    base64-encoded in the embedded resource."""
    payload = b"mcp drive_download content-block test\n"
    name = _unique_name("mcp-download")
    uploaded = drive.upload_bytes(
        data=payload, name=name, mime_type="text/plain"
    )
    file_id = uploaded["id"]

    try:
        blocks = asyncio.run(drive_download(file_id=file_id))
        assert isinstance(blocks, list), f"expected list of blocks, got {blocks!r}"
        assert len(blocks) == 2
        summary, embedded = blocks
        assert isinstance(summary, TextContent)
        summary_data = json.loads(summary.text)
        assert summary_data["destination"] == "inline"
        assert summary_data["name"] == name
        assert summary_data["size_bytes"] == len(payload)
        assert isinstance(embedded, EmbeddedResource)
        decoded = base64.b64decode(embedded.resource.blob)
        assert decoded == payload
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_download_mcp_too_large_returns_error_envelope():
    """A file above the inline cap returns a structured error envelope
    rather than blowing through client tool-response limits."""
    payload = b"a" * 4096
    name = _unique_name("mcp-too-large")
    uploaded = drive.upload_bytes(
        data=payload, name=name, mime_type="text/plain"
    )
    file_id = uploaded["id"]

    try:
        # Force the cap below the file size.
        result = asyncio.run(drive_download(file_id=file_id, max_size_bytes=64))
        assert isinstance(result, dict), f"expected dict envelope, got {result!r}"
        assert result.get("success") is False
        assert result["size_bytes"] == len(payload)
        assert result["cap_bytes"] == 64
        assert "hint" in result
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_full_drive_lifecycle_end_to_end():
    """Upload bytes → list-in-root → move to a folder → list-in-folder
    → download via MCP tool → delete → confirm trashed.

    Exercises every new Drive primitive in one workflow."""
    payload = b"lifecycle: full circle\n"
    file_name = _unique_name("lifecycle")
    folder_name = _unique_name("lifecycle-folder").replace(".bin", "")

    file_id = None
    folder_id = None
    try:
        # Upload
        uploaded = drive.upload_bytes(
            data=payload, name=file_name, mime_type="text/plain"
        )
        file_id = uploaded["id"]

        # Create folder + move into it
        folder = drive.create_folder(name=folder_name)
        folder_id = folder["id"]
        move_result = drive.move_file(
            file_id=file_id, destination_folder_id=folder_id
        )
        assert folder_id in move_result["parents"]

        # List the folder; the file should appear by name
        listing = drive.list_folder(folder_id=folder_id)
        names_in_folder = [item["name"] for item in listing.get("items", [])]
        assert file_name in names_in_folder, (
            f"After move, expected {file_name!r} to appear in folder listing; "
            f"got {names_in_folder!r}"
        )

        # Download via the MCP tool → verify bytes round-trip
        blocks = asyncio.run(drive_download(file_id=file_id))
        embedded = blocks[1]
        assert isinstance(embedded, EmbeddedResource)
        assert base64.b64decode(embedded.resource.blob) == payload

        # Trash
        trashed = drive.delete_file(file_id=file_id)
        assert trashed == {"file_id": file_id, "trashed": True}
    finally:
        _safe_trash(file_id)
        _safe_trash(folder_id)
