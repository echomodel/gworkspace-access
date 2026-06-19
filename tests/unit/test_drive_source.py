"""Unit tests for Drive upload/update/download tools.

Sociable: real SDK + MCP code paths with a fake Drive service injected at
the service-factory boundary, and the resumable-session initiator
monkeypatched (it would otherwise hit Google). No mcp-app server, no
network.

Transport-safety model: the **network-exposed** tools never read or write a
caller-named server path. They take bytes (``content_base64``) or hand back
an out-of-band Google URL. Reading/writing a **local path** lives in separate
``@mcp_transport("stdio")`` tools (``drive_upload_local``,
``drive_update_local``, ``drive_download_to_path``), which the framework only
registers over stdio — where the server runs as the local user, so touching
their own disk is no privilege escalation.
"""

from __future__ import annotations

import base64
import inspect

import pytest

from gwsa.mcp.tools import drive as drive_tools
from gwsa.sdk.sources import (
    DEFAULT_INLINE_SOURCE_CAP_BYTES,
    InlineSourceTooLargeError,
    InvalidInlineSourceError,
    decode_inline_upload,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _transports(fn):
    return getattr(fn, "_mcp_transports", None)


# --- decode_inline_upload — the SDK boundary -------------------------


def test_decode_inline_decodes_and_guesses_mime():
    data = b"%PDF-1.4 fake pdf bytes"
    out, name, mime = decode_inline_upload(_b64(data), name="report.pdf")
    assert out == data
    assert name == "report.pdf"
    assert mime == "application/pdf"


def test_decode_inline_explicit_mime_wins():
    _d, _n, mime = decode_inline_upload(_b64(b"x"), name="t.bin", mime_type="image/png")
    assert mime == "image/png"


def test_decode_inline_rejects_oversize():
    big = b"a" * (DEFAULT_INLINE_SOURCE_CAP_BYTES + 1)
    with pytest.raises(InlineSourceTooLargeError):
        decode_inline_upload(_b64(big), name="big.bin")


def test_decode_inline_custom_cap():
    with pytest.raises(InlineSourceTooLargeError):
        decode_inline_upload(_b64(b"a" * 100), name="x", max_size_bytes=50)


def test_decode_inline_invalid_base64():
    with pytest.raises(InvalidInlineSourceError):
        decode_inline_upload("not!!valid!!base64", name="x")


# --- fake Drive service ----------------------------------------------


class FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeFiles:
    def __init__(self, store):
        self._store = store

    def create(self, body, media_body, fields, **kwargs):
        self._store["create"] = {"body": body, "media": media_body, "kwargs": kwargs}
        return FakeExecute({
            "id": "new-file-id",
            "name": body.get("name"),
            "webViewLink": "https://drive.google.com/file/d/new-file-id",
        })

    def update(self, fileId, body, media_body, fields, **kwargs):
        self._store["update"] = {
            "fileId": fileId, "body": body, "media": media_body, "kwargs": kwargs,
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
    monkeypatch.setattr(
        "gwsa.sdk.drive.upload.get_drive_service",
        lambda account=None: FakeDriveService(store),
    )
    return store


# --- drive_upload (inline / out-of-band; all transports) -------------


@pytest.mark.asyncio
async def test_drive_upload_inline_round_trips(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_upload(
        content_base64=_b64(b"%PDF fake"), name="statement.pdf",
        folder_id="folder-123",
    )
    assert result["id"] == "new-file-id"
    assert result["name"] == "statement.pdf"
    assert store["create"]["body"]["parents"] == ["folder-123"]
    assert store["create"]["kwargs"].get("supportsAllDrives") is True


@pytest.mark.asyncio
async def test_drive_upload_inline_requires_name(patch_drive_service):
    result = await drive_tools.drive_upload(content_base64=_b64(b"x"))
    assert "error" in result


@pytest.mark.asyncio
async def test_drive_upload_oversize_inline_returns_error_envelope(patch_drive_service):
    big = b"a" * (DEFAULT_INLINE_SOURCE_CAP_BYTES + 1)
    result = await drive_tools.drive_upload(content_base64=_b64(big), name="big.bin")
    assert result["success"] is False
    assert result["cap_bytes"] == DEFAULT_INLINE_SOURCE_CAP_BYTES
    assert "drive_upload_local" in result["hint"]


@pytest.mark.asyncio
async def test_drive_upload_name_only_returns_session_url(monkeypatch):
    monkeypatch.setattr(
        "gwsa.sdk.drive.begin_resumable_upload",
        lambda **kw: "https://www.googleapis.com/upload/...&upload_id=ABC",
    )
    # No content + a name → direct-to-Google resumable URL (works over HTTP,
    # no server-side file read).
    result = await drive_tools.drive_upload(name="big.bin")
    assert result["mode"] == "out_of_band"
    assert result["upload_url"].endswith("upload_id=ABC")
    assert "curl -fL -T" in result["run"]


@pytest.mark.asyncio
async def test_drive_upload_no_content_no_name_errors():
    result = await drive_tools.drive_upload()
    assert "error" in result


# --- drive_upload_local (stdio only) ---------------------------------


@pytest.mark.asyncio
async def test_drive_upload_local_reads_and_uploads(patch_drive_service, tmp_path):
    p = tmp_path / "local.txt"
    p.write_bytes(b"server-readable content")
    result = await drive_tools.drive_upload_local(local_path=str(p))
    assert result["name"] == "local.txt"  # derived from basename
    assert "error" not in result


@pytest.mark.asyncio
async def test_drive_upload_local_missing_file_errors():
    result = await drive_tools.drive_upload_local(local_path="/no/such/file.bin")
    assert "File not found" in result["error"]


# --- drive_update (inline / out-of-band; all transports) -------------


@pytest.mark.asyncio
async def test_drive_update_inline_round_trips(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_update(
        file_id="existing-id", content_base64=_b64(b"new content"),
        name="renamed-v2.pdf",
    )
    assert store["update"]["fileId"] == "existing-id"
    assert store["update"]["body"]["name"] == "renamed-v2.pdf"
    assert store["update"]["kwargs"].get("supportsAllDrives") is True
    assert result["id"] == "existing-id"


@pytest.mark.asyncio
async def test_drive_update_no_content_returns_session_url(monkeypatch):
    monkeypatch.setattr(
        "gwsa.sdk.drive.begin_resumable_update",
        lambda **kw: "https://www.googleapis.com/upload/...&upload_id=UPD",
    )
    result = await drive_tools.drive_update(file_id="f1")
    assert result["mode"] == "out_of_band"
    assert result["upload_url"].endswith("upload_id=UPD")
    assert "curl -fL -T" in result["run"]


@pytest.mark.asyncio
async def test_drive_update_local_missing_file_errors():
    result = await drive_tools.drive_update_local(file_id="f1", local_path="/no/such.bin")
    assert "File not found" in result["error"]


# --- security boundary: host-path I/O must stay off the HTTP surface --


def test_network_tools_take_no_server_path():
    """The all-transports tools must not expose a server-side path param —
    that would be an arbitrary server-file read/write over HTTP."""
    assert _transports(drive_tools.drive_upload) is None      # unannotated = all
    assert "local_path" not in inspect.signature(drive_tools.drive_upload).parameters
    assert _transports(drive_tools.drive_update) is None
    assert "local_path" not in inspect.signature(drive_tools.drive_update).parameters
    assert _transports(drive_tools.drive_download) is None
    assert "save_to" not in inspect.signature(drive_tools.drive_download).parameters


def test_host_path_tools_are_stdio_only():
    """The path-reading/-writing tools exist only over stdio."""
    for fn in (
        drive_tools.drive_upload_local,
        drive_tools.drive_update_local,
        drive_tools.drive_download_to_path,
    ):
        assert _transports(fn) == frozenset({"stdio"}), fn.__name__
