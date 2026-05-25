"""Integration tests for ``drive_search`` and ``drive_get_metadata``
against real Drive.

Self-contained: each test creates its own uniquely-named scratch file
or folder, exercises the read path, and cleans up. No reliance on
pre-existing files in the user's Drive.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from gwsa.mcp.tools.drive import drive_get_metadata, drive_search
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
def test_get_metadata_round_trips_against_real_drive():
    payload = b"metadata roundtrip"
    name = _unique("metadata-roundtrip") + ".txt"
    uploaded = drive.upload_bytes(data=payload, name=name, mime_type="text/plain")
    file_id = uploaded["id"]

    try:
        meta = drive.get_metadata(file_id=file_id)
        assert meta["id"] == file_id
        assert meta["name"] == name
        assert meta["mime_type"] == "text/plain"
        # Drive returns size as a string; cast for the comparison.
        assert int(meta["size"]) == len(payload)
        assert meta["trashed"] is False
        assert meta["parents"], "expected at least one parent (root)"
        assert meta["url"].startswith("https://"), meta["url"]
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_get_metadata_reports_trashed_after_delete():
    name = _unique("trash-meta") + ".txt"
    uploaded = drive.upload_bytes(data=b"x", name=name, mime_type="text/plain")
    file_id = uploaded["id"]
    cleanup_needed = True
    try:
        drive.delete_file(file_id=file_id)
        cleanup_needed = False
        meta = drive.get_metadata(file_id=file_id)
        # Still resolvable (Trash semantics, not hard-delete).
        assert meta["id"] == file_id
        assert meta["trashed"] is True
    finally:
        if cleanup_needed:
            _safe_trash(file_id)


@pytest.mark.integration
def test_drive_get_metadata_mcp_tool_happy_path():
    name = _unique("mcp-meta") + ".txt"
    uploaded = drive.upload_bytes(data=b"mcp meta", name=name, mime_type="text/plain")
    file_id = uploaded["id"]
    try:
        result = asyncio.run(drive_get_metadata(file_id=file_id))
        assert "error" not in result, result
        assert result["id"] == file_id
        assert result["name"] == name
        assert int(result["size"]) == len(b"mcp meta")
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_get_metadata_mcp_tool_returns_envelope_for_missing_file():
    """Bare ``files.get`` on a fake id should produce an error envelope,
    not raise — the tool wraps SDK exceptions into ``{error: ...}``."""
    result = asyncio.run(drive_get_metadata(file_id="this-id-does-not-exist-9999"))
    assert "error" in result, result


@pytest.mark.integration
def test_search_drive_finds_uploaded_file_by_name():
    """A freshly uploaded file with a unique name is findable via
    ``drive_search`` using ``name contains``."""
    needle = _unique("search-needle")
    name = f"{needle}.txt"
    uploaded = drive.upload_bytes(data=b"findme", name=name, mime_type="text/plain")
    file_id = uploaded["id"]
    try:
        # Drive's search index can lag a moment behind file creation.
        # Retry a few times with backoff rather than failing on a race.
        found = None
        deadline = time.time() + 20
        while time.time() < deadline:
            result = drive.search_drive(
                query=f"name contains '{needle}' and trashed = false",
                max_results=10,
            )
            for item in result["items"]:
                if item["id"] == file_id:
                    found = item
                    break
            if found:
                break
            time.sleep(2)
        assert found is not None, (
            f"Uploaded file {name!r} did not surface in search within 20s"
        )
        assert found["name"] == name
        assert found["mime_type"] == "text/plain"
        assert int(found["size"]) == len(b"findme")
        assert found["parents"], "expected parents to be populated"
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_search_mcp_returns_items_and_next_page_token_shape():
    """The MCP tool returns the SDK shape unchanged: an items list
    plus a (possibly-None) next_page_token."""
    needle = _unique("mcp-search")
    name = f"{needle}.txt"
    uploaded = drive.upload_bytes(data=b"x", name=name, mime_type="text/plain")
    file_id = uploaded["id"]
    try:
        # Same indexing-lag tolerance.
        result = None
        deadline = time.time() + 20
        while time.time() < deadline:
            candidate = asyncio.run(
                drive_search(
                    query=f"name contains '{needle}' and trashed = false",
                    max_results=10,
                )
            )
            if any(item["id"] == file_id for item in candidate.get("items", [])):
                result = candidate
                break
            time.sleep(2)
        assert result is not None, "uploaded file did not surface within 20s"
        assert "items" in result and isinstance(result["items"], list)
        assert "next_page_token" in result
    finally:
        _safe_trash(file_id)


@pytest.mark.integration
def test_drive_search_filters_by_mime_type_folder():
    """Folder-only filter (the recipe ``drive_search_folders`` uses
    under the hood) returns only folders."""
    folder = drive.create_folder(name=_unique("search-folder-filter"))
    folder_id = folder["id"]
    try:
        result = drive.search_drive(
            query=(
                "mimeType = 'application/vnd.google-apps.folder' "
                "and trashed = false"
            ),
            max_results=25,
        )
        for item in result["items"]:
            assert item["mime_type"] == "application/vnd.google-apps.folder", (
                f"folder-only filter returned non-folder: {item!r}"
            )
    finally:
        _safe_trash(folder_id)
