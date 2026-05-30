"""Unit tests for transport-safe Drive upload/update via the Source shape.

Sociable tests: real SDK + MCP code paths, a fake Drive service injected
at the service-factory boundary. No mcp-app server, no network.

The bug these guard against: ``drive_upload`` / ``drive_update`` used to
take only a server-local ``local_path``. Under HTTP transport the server
cannot read the agent's filesystem, so every upload of a real local file
failed with errno-2 / 404. The ``source`` discriminated union adds an
inline base64 path that works under any transport.
"""

from __future__ import annotations

import base64

import pytest

from gwsa.mcp.tools import drive as drive_tools
from gwsa.sdk.sources import (
    DEFAULT_INLINE_SOURCE_CAP_BYTES,
    InlineSource,
    InlineSourceTooLargeError,
    InvalidInlineSourceError,
    LocalPathSource,
    resolve_source,
)


# ---------------------------------------------------------------------------
# resolve_source — the SDK boundary
# ---------------------------------------------------------------------------


def test_resolve_inline_decodes_and_guesses_mime():
    data = b"%PDF-1.4 fake pdf bytes"
    src = InlineSource(
        data_base64=base64.b64encode(data).decode(), name="report.pdf"
    )
    out_data, name, mime = resolve_source(src)
    assert out_data == data
    assert name == "report.pdf"
    assert mime == "application/pdf"


def test_resolve_inline_explicit_mime_wins():
    src = InlineSource(
        data_base64=base64.b64encode(b"x").decode(),
        name="thing.bin",
        mime_type="image/png",
    )
    _data, _name, mime = resolve_source(src)
    assert mime == "image/png"


def test_resolve_inline_rejects_oversize():
    big = b"a" * (DEFAULT_INLINE_SOURCE_CAP_BYTES + 1)
    src = InlineSource(
        data_base64=base64.b64encode(big).decode(), name="big.bin"
    )
    with pytest.raises(InlineSourceTooLargeError):
        resolve_source(src)


def test_resolve_inline_custom_cap():
    data = b"a" * 100
    src = InlineSource(
        data_base64=base64.b64encode(data).decode(),
        name="x", max_size_bytes=50,
    )
    with pytest.raises(InlineSourceTooLargeError):
        resolve_source(src)


def test_resolve_inline_invalid_base64():
    src = InlineSource(data_base64="not!!valid!!base64", name="x")
    with pytest.raises(InvalidInlineSourceError):
        resolve_source(src)


def test_resolve_path_reads_file(tmp_path):
    p = tmp_path / "doc.txt"
    p.write_bytes(b"hello from disk")
    data, name, mime = resolve_source(LocalPathSource(path=str(p)))
    assert data == b"hello from disk"
    assert name == "doc.txt"
    assert mime == "text/plain"


def test_resolve_path_missing_raises():
    with pytest.raises(FileNotFoundError):
        resolve_source(LocalPathSource(path="/no/such/file.bin"))


# ---------------------------------------------------------------------------
# MCP tools — drive_upload / drive_update with a fake Drive service
# ---------------------------------------------------------------------------


class FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeFiles:
    def __init__(self, store):
        self._store = store

    def create(self, body, media_body, fields, **kwargs):
        self._store["create"] = {
            "body": body, "media": media_body, "kwargs": kwargs,
        }
        return FakeExecute({
            "id": "new-file-id",
            "name": body.get("name"),
            "webViewLink": "https://drive.google.com/file/d/new-file-id",
        })

    def update(self, fileId, body, media_body, fields, **kwargs):
        self._store["update"] = {
            "fileId": fileId, "body": body, "media": media_body,
            "kwargs": kwargs,
        }
        return FakeExecute({
            "id": fileId,
            "name": body.get("name", "existing"),
            "webViewLink": f"https://drive.google.com/file/d/{fileId}",
        })


class FakeDriveService:
    def __init__(self, store):
        self._store = store

    def files(self):
        return FakeFiles(self._store)


@pytest.fixture
def patch_drive_service(monkeypatch):
    store: dict = {}

    def fake_factory(account=None):
        return FakeDriveService(store)

    # upload_bytes / update_bytes resolve the service via this factory
    monkeypatch.setattr(
        "gwsa.sdk.drive.upload.get_drive_service", fake_factory
    )
    return store


def _inline(data: bytes, name: str, mime=None) -> InlineSource:
    return InlineSource(
        data_base64=base64.b64encode(data).decode(), name=name, mime_type=mime
    )


@pytest.mark.asyncio
async def test_drive_upload_inline_round_trips(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_upload(
        source=_inline(b"%PDF fake", "statement.pdf"),
        folder_id="folder-123",
    )
    assert result["id"] == "new-file-id"
    assert result["name"] == "statement.pdf"
    # the bytes reached the Drive create call as a media upload
    assert store["create"]["body"]["name"] == "statement.pdf"
    assert store["create"]["body"]["parents"] == ["folder-123"]


@pytest.mark.asyncio
async def test_drive_upload_passes_supports_all_drives(patch_drive_service):
    """Regression: uploads into a Shared Drive / shared folder 404 on the
    parent unless supportsAllDrives=True is sent. Every other Drive
    mutation sets it; create/update must too."""
    store = patch_drive_service
    await drive_tools.drive_upload(
        source=_inline(b"data", "x.bin"), folder_id="shared-folder",
    )
    assert store["create"]["kwargs"].get("supportsAllDrives") is True


@pytest.mark.asyncio
async def test_drive_update_passes_supports_all_drives(patch_drive_service):
    store = patch_drive_service
    await drive_tools.drive_update(
        file_id="f1", source=_inline(b"data", "x.bin"),
    )
    assert store["update"]["kwargs"].get("supportsAllDrives") is True


@pytest.mark.asyncio
async def test_drive_upload_inline_from_a_real_local_file(
    patch_drive_service, tmp_path
):
    """End-to-end shape for the common case: a local file read by the
    agent, sent inline, landing in a folder under HTTP transport."""
    pdf = tmp_path / "hd-statement.pdf"
    pdf.write_bytes(b"%PDF-1.7 " + b"x" * 500)
    src = _inline(pdf.read_bytes(), "2026-05-18_statement.pdf")

    result = await drive_tools.drive_upload(source=src, folder_id="bills")
    assert result["name"] == "2026-05-18_statement.pdf"
    assert "error" not in result


@pytest.mark.asyncio
async def test_drive_upload_path_source_under_stdio(
    patch_drive_service, tmp_path
):
    p = tmp_path / "local.txt"
    p.write_bytes(b"server-readable content")
    result = await drive_tools.drive_upload(
        source=LocalPathSource(path=str(p)),
    )
    assert result["name"] == "local.txt"  # derived from basename
    assert "error" not in result


@pytest.mark.asyncio
async def test_drive_upload_name_override(patch_drive_service):
    result = await drive_tools.drive_upload(
        source=_inline(b"data", "original.bin"),
        name="renamed.bin",
    )
    assert result["name"] == "renamed.bin"


@pytest.mark.asyncio
async def test_drive_upload_oversize_inline_returns_error_envelope(
    patch_drive_service,
):
    big = b"a" * (DEFAULT_INLINE_SOURCE_CAP_BYTES + 1)
    result = await drive_tools.drive_upload(source=_inline(big, "big.bin"))
    assert result["success"] is False
    assert result["cap_bytes"] == DEFAULT_INLINE_SOURCE_CAP_BYTES
    assert "stdio" in result["hint"]


@pytest.mark.asyncio
async def test_drive_upload_missing_path_returns_error(patch_drive_service):
    result = await drive_tools.drive_upload(
        source=LocalPathSource(path="/no/such/file.pdf"),
    )
    assert "error" in result
    assert "inline" in result["error"].lower()


@pytest.mark.asyncio
async def test_drive_update_inline_round_trips(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_update(
        file_id="existing-id",
        source=_inline(b"new content", "v2.pdf"),
        name="renamed-v2.pdf",
    )
    assert store["update"]["fileId"] == "existing-id"
    assert store["update"]["body"]["name"] == "renamed-v2.pdf"
    assert result["id"] == "existing-id"
