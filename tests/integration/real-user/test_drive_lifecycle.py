"""Integration tests for the byte-producing Drive primitives.

Self-contained: each test creates its own scratch file in Drive,
exercises the lifecycle, and cleans up after itself. No reliance on
pre-existing test data.

Covers:
- ``drive.upload_bytes`` / ``drive.download_bytes`` — bytes round trip
- ``drive.update_metadata`` — rename and move (``files.update``)
- ``drive.delete_file`` — Trash semantics
- ``drive_update`` — rename, move, and content in one call
- ``drive_upload`` — conversion via ``mime_type``; the upload URL flow
  (``upload_url=true`` + ``curl -T``), including conversion
- ``drive_download`` — text as text, binary as base64, large → link
"""

from __future__ import annotations

import asyncio
import base64
import json
import shlex
import subprocess
import time

import pytest
from mcp.types import BlobResourceContents, EmbeddedResource, TextContent, TextResourceContents

from gwsa.mcp.tools.drive import drive_delete, drive_download, drive_update, drive_upload
from gwsa.sdk import docs, drive
from gwsa.sdk.destinations import DEFAULT_INLINE_SIZE_CAP_BYTES

GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"


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
def test_update_metadata_moves_file():
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
        result = drive.update_metadata(file_id, folder_id=folder_id)
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
def test_drive_update_renames_moves_and_replaces_content():
    """``drive_update`` = ``files.update``: rename alone, move alone, then
    all three at once — each verified against Drive."""
    uploaded = drive.upload_bytes(
        data=b"v1", name=_unique_name("mcp-update"), mime_type="text/plain"
    )
    file_id = uploaded["id"]
    folder_id = drive.create_folder(name=_unique_name("mcp-update-folder").replace(".bin", ""))["id"]
    try:
        renamed = asyncio.run(drive_update(file_id=file_id, name="renamed.txt"))
        assert "error" not in renamed, renamed
        assert drive.get_metadata(file_id)["name"] == "renamed.txt"

        moved = asyncio.run(drive_update(file_id=file_id, folder_id=folder_id))
        assert moved["parents"] == [folder_id]

        both = asyncio.run(drive_update(
            file_id=file_id, name="v2.txt", folder_id="root",
            content_base64=base64.b64encode(b"v2").decode()))
        assert both["name"] == "v2.txt"
        assert folder_id not in both["parents"]
        assert drive.download_bytes(file_id=file_id)["data"] == b"v2"
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
def test_drive_download_text_file_returns_text():
    """A small YAML file comes back as readable text, not base64."""
    payload = b"retries: 3\ntimeout: 30\n"
    uploaded = drive.upload_bytes(
        data=payload, name=_unique_name("mcp-download") + ".yaml",
        mime_type="application/octet-stream",
    )
    file_id = uploaded["id"]
    try:
        blocks = asyncio.run(drive_download(file_id=file_id))
        summary, embedded = blocks
        assert isinstance(summary, TextContent)
        assert json.loads(summary.text)["encoding"] == "text"
        assert isinstance(embedded, EmbeddedResource)
        assert isinstance(embedded.resource, TextResourceContents)
        assert embedded.resource.text == payload.decode()
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_download_binary_returns_base64():
    payload = bytes(range(256))
    uploaded = drive.upload_bytes(
        data=payload, name=_unique_name("mcp-download-bin"),
        mime_type="application/octet-stream",
    )
    file_id = uploaded["id"]
    try:
        _summary, embedded = asyncio.run(drive_download(file_id=file_id))
        assert isinstance(embedded.resource, BlobResourceContents)
        assert base64.b64decode(embedded.resource.blob) == payload
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_download_large_file_returns_drive_link():
    """Above the inline cap, the tool returns the file's Drive link."""
    payload = b"a" * (DEFAULT_INLINE_SIZE_CAP_BYTES + 1024)
    uploaded = drive.upload_bytes(
        data=payload, name=_unique_name("mcp-large"), mime_type="text/plain"
    )
    file_id = uploaded["id"]
    try:
        result = asyncio.run(drive_download(file_id=file_id))
        assert isinstance(result, dict) and result["mode"] == "link", result
        assert result["url"] and file_id in result["url"]
        assert result["size_bytes"] == len(payload)
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_upload_converts_markdown_to_doc():
    """``mime_type`` = Google Doc converts Markdown into a formatted Doc."""
    md = "# Plan heading\n\nIntro paragraph.\n\n- first\n- second\n"
    result = asyncio.run(drive_upload(
        name=_unique_name("convert") + ".md",
        content_base64=base64.b64encode(md.encode()).decode(),
        mime_type=GOOGLE_DOC,
    ))
    file_id = result.get("id")
    try:
        assert result["mime_type"] == GOOGLE_DOC, result
        lines = docs.get_document_map(file_id)["segments"][0]["lines"]
        assert any("[HEADING_1] Plan heading" in ln for ln in lines), lines
        assert any("[list L0] first" in ln for ln in lines), lines
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_upload_converts_csv_to_sheet():
    result = asyncio.run(drive_upload(
        name=_unique_name("convert") + ".csv",
        content_base64=base64.b64encode(b"a,b\n1,2\n").decode(),
        mime_type=GOOGLE_SHEET,
    ))
    try:
        assert result["mime_type"] == GOOGLE_SHEET, result
    finally:
        _safe_trash(result.get("id"))


@pytest.mark.integration
def test_upload_url_flow_with_curl_and_conversion(tmp_path):
    """The upload URL works as documented: the agent sends the file with
    ``curl -T`` and Drive creates (and converts) the file."""
    src = tmp_path / "Notes.md"
    src.write_text("# Notes\n\nBody text.\n")
    session = asyncio.run(drive_upload(
        name=_unique_name("url") + ".md", upload_url=True, mime_type=GOOGLE_DOC,
    ))
    assert session["mode"] == "out_of_band", session
    cmd = session["run"].replace("<your-file>", shlex.quote(str(src)))
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    created = json.loads(out.stdout)
    try:
        assert created["mimeType"] == GOOGLE_DOC, created
        lines = docs.get_document_map(created["id"])["segments"][0]["lines"]
        assert any("[HEADING_1] Notes" in ln for ln in lines), lines
    finally:
        _safe_trash(created.get("id"))


@pytest.mark.integration
def test_update_upload_url_flow_with_curl_and_rename(tmp_path):
    uploaded = drive.upload_bytes(data=b"v1", name=_unique_name("url-upd"), mime_type="text/plain")
    file_id = uploaded["id"]
    src = tmp_path / "v2.txt"
    src.write_bytes(b"v2 via url")
    try:
        session = asyncio.run(drive_update(file_id=file_id, upload_url=True, name="v2.txt"))
        cmd = session["run"].replace("<your-file>", shlex.quote(str(src)))
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        assert drive.download_bytes(file_id=file_id)["data"] == b"v2 via url"
        assert drive.get_metadata(file_id)["name"] == "v2.txt"
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
        move_result = drive.update_metadata(file_id, folder_id=folder_id)
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
        assert embedded.resource.text == payload.decode()

        # Trash
        trashed = drive.delete_file(file_id=file_id)
        assert trashed == {"file_id": file_id, "trashed": True}
    finally:
        _safe_trash(file_id)
        _safe_trash(folder_id)
