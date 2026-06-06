"""Unit tests for transport-aware Drive upload/update.

Sociable: real SDK + MCP code paths with a fake Drive service injected at
the service-factory boundary, and the resumable-session initiator
monkeypatched (it would otherwise hit Google). No mcp-app server, no
network.

The tools choose transport from context, never from a caller-supplied
union:
- ``content_base64`` → small inline upload (any transport).
- ``local_path`` → if the server can see the file (stdio), read + upload
  directly (any size); otherwise (remote/HTTP) return a direct-to-Google
  resumable session URL to PUT the bytes to.
Transport is detected by whether the path is visible on the server's
filesystem — no framework dependency.
"""

from __future__ import annotations

import base64

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


# --- drive_upload (stdio / inline) -----------------------------------


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
    assert "local_path" in result["hint"]


@pytest.mark.asyncio
async def test_drive_upload_local_path_under_stdio(patch_drive_service, tmp_path):
    p = tmp_path / "local.txt"
    p.write_bytes(b"server-readable content")
    result = await drive_tools.drive_upload(local_path=str(p))
    assert result["name"] == "local.txt"  # derived from basename
    assert "error" not in result


# --- drive_upload (remote / out-of-band) -----------------------------
# Transport is detected by whether the server can see the file: a path
# the server cannot stat means a remote (HTTP) caller, so the tool hands
# back a direct-to-Google resumable session URL.


@pytest.mark.asyncio
async def test_drive_upload_unreadable_path_returns_session_url(monkeypatch):
    monkeypatch.setattr(
        "gwsa.sdk.drive.begin_resumable_upload",
        lambda **kw: "https://www.googleapis.com/upload/...&upload_id=ABC",
    )
    # Path the server can't see → treated as remote → session URL.
    result = await drive_tools.drive_upload(local_path="/agent/only/big.bin")
    assert result["mode"] == "out_of_band"
    assert result["upload_url"].endswith("upload_id=ABC")
    assert "curl -fL -T" in result["run"]
    assert "/agent/only/big.bin" in result["run"]


@pytest.mark.asyncio
async def test_drive_upload_no_content_no_path_needs_name():
    result = await drive_tools.drive_upload()
    assert "error" in result


# --- drive_update ----------------------------------------------------


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
async def test_drive_update_unreadable_path_returns_session_url(monkeypatch):
    monkeypatch.setattr(
        "gwsa.sdk.drive.begin_resumable_update",
        lambda **kw: "https://www.googleapis.com/upload/...&upload_id=UPD",
    )
    result = await drive_tools.drive_update(file_id="f1", local_path="/agent/only/v2.bin")
    assert result["mode"] == "out_of_band"
    assert result["upload_url"].endswith("upload_id=UPD")
    assert "curl -fL -T" in result["run"]
