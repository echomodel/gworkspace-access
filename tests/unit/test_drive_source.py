"""Unit tests for Drive upload/update/download tools.

Sociable: real SDK + MCP code paths with a fake Drive service injected at
the service-factory boundary, and the resumable-session initiator
monkeypatched (it would otherwise hit Google). No mcp-app server, no
network.

Transport-safety model: the **network-exposed** tools never read or write a
caller-named server path. They take bytes (``content_base64``) or hand back
an out-of-band Google URL. Reading/writing a **local path** lives in separate
``@mcp_transport("stdio")`` tools (``drive_create_file_local``,
``drive_update_file_local``, ``drive_download_to_path``), which the framework only
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

    def update(self, fileId, body, fields, media_body=None, **kwargs):
        self._store["update"] = {
            "fileId": fileId, "body": body, "media": media_body, "kwargs": kwargs,
        }
        parents = [kwargs["addParents"]] if "addParents" in kwargs else ["old-folder"]
        return FakeExecute({
            "id": fileId,
            "name": body.get("name", "existing"),
            "parents": parents,
            "webViewLink": f"https://drive.google.com/file/d/{fileId}",
        })

    def get(self, fileId, fields, **kwargs):
        return FakeExecute({"parents": ["old-folder"]})


class FakeDriveService:
    def __init__(self, store):
        self._store = store

    def files(self):
        return FakeFiles(self._store)


@pytest.fixture
def patch_drive_service(monkeypatch):
    store: dict = {}
    for mod in ("gwsa.sdk.drive.upload", "gwsa.sdk.drive.files"):
        monkeypatch.setattr(
            f"{mod}.get_drive_service",
            lambda account=None: FakeDriveService(store),
        )
    return store


# --- drive_create_file (inline / out-of-band; all transports) -------------


@pytest.mark.asyncio
async def test_drive_upload_inline_round_trips(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_create_file(
        content_base64=_b64(b"%PDF fake"), name="statement.pdf",
        folder_id="folder-123",
    )
    assert result["id"] == "new-file-id"
    assert result["name"] == "statement.pdf"
    assert store["create"]["body"]["parents"] == ["folder-123"]
    assert store["create"]["kwargs"].get("supportsAllDrives") is True


@pytest.mark.asyncio
async def test_drive_upload_inline_requires_name(patch_drive_service):
    result = await drive_tools.drive_create_file(content_base64=_b64(b"x"))
    assert "error" in result


@pytest.mark.asyncio
async def test_drive_upload_oversize_inline_returns_error_envelope(patch_drive_service):
    big = b"a" * (DEFAULT_INLINE_SOURCE_CAP_BYTES + 1)
    result = await drive_tools.drive_create_file(content_base64=_b64(big), name="big.bin")
    assert result["success"] is False
    assert result["cap_bytes"] == DEFAULT_INLINE_SOURCE_CAP_BYTES
    assert "drive_create_file_local" in result["hint"]


@pytest.mark.asyncio
async def test_drive_upload_upload_url_returns_session_url(monkeypatch):
    calls = {}
    def fake(**kw):
        calls.update(kw)
        return "https://www.googleapis.com/upload/...&upload_id=ABC"
    monkeypatch.setattr("gwsa.sdk.drive.begin_resumable_upload", fake)
    # upload_url=True + a name → direct-to-Google upload URL (works over
    # HTTP, no server-side file read).
    result = await drive_tools.drive_create_file(name="big.bin", upload_url=True)
    assert result["mode"] == "out_of_band"
    assert result["upload_url"].endswith("upload_id=ABC")
    assert "curl -fL -T" in result["run"]
    assert calls["name"] == "big.bin" and calls["file_mime_type"] is None


@pytest.mark.asyncio
async def test_drive_upload_name_only_is_not_an_upload_url_request():
    result = await drive_tools.drive_create_file(name="big.bin")
    assert "error" in result and "upload_url" in result["error"]


@pytest.mark.asyncio
async def test_drive_upload_upload_url_needs_name_and_no_content():
    assert "name" in (await drive_tools.drive_create_file(upload_url=True))["error"]
    r = await drive_tools.drive_create_file(name="a.txt", content_base64=_b64(b"x"), upload_url=True)
    assert "not both" in r["error"]


@pytest.mark.asyncio
async def test_drive_upload_converts_with_target_mime_type(patch_drive_service):
    store = patch_drive_service
    await drive_tools.drive_create_file(
        content_base64=_b64(b"# Plan\n\n- one\n"), name="Plan.md",
        mime_type="application/vnd.google-apps.document",
    )
    body = store["create"]["body"]
    assert body["mimeType"] == "application/vnd.google-apps.document"
    assert store["create"]["media"].mimetype() == "text/markdown"


@pytest.mark.asyncio
async def test_drive_upload_without_mime_type_stores_as_is(patch_drive_service):
    store = patch_drive_service
    await drive_tools.drive_create_file(content_base64=_b64(b"a,b\n"), name="t.csv")
    assert "mimeType" not in store["create"]["body"]


@pytest.mark.asyncio
async def test_drive_upload_url_with_conversion_passes_content_type(monkeypatch):
    calls = {}
    monkeypatch.setattr("gwsa.sdk.drive.begin_resumable_upload",
                        lambda **kw: calls.update(kw) or "https://x/?upload_id=Z")
    await drive_tools.drive_create_file(
        name="Sheet.csv", upload_url=True,
        mime_type="application/vnd.google-apps.spreadsheet",
    )
    assert calls["mime_type"] == "text/csv"
    assert calls["file_mime_type"] == "application/vnd.google-apps.spreadsheet"


@pytest.mark.asyncio
async def test_drive_upload_no_content_no_name_errors():
    result = await drive_tools.drive_create_file()
    assert "error" in result


# --- drive_create_file_local (stdio only) ---------------------------------


@pytest.mark.asyncio
async def test_drive_upload_local_reads_and_uploads(patch_drive_service, tmp_path):
    p = tmp_path / "local.txt"
    p.write_bytes(b"server-readable content")
    result = await drive_tools.drive_create_file_local(local_path=str(p))
    assert result["name"] == "local.txt"  # derived from basename
    assert "error" not in result


@pytest.mark.asyncio
async def test_drive_upload_local_missing_file_errors():
    result = await drive_tools.drive_create_file_local(local_path="/no/such/file.bin")
    assert "File not found" in result["error"]


# --- drive_update_file (inline / out-of-band; all transports) -------------


@pytest.mark.asyncio
async def test_drive_update_inline_round_trips(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_update_file(
        file_id="existing-id", content_base64=_b64(b"new content"),
        name="renamed-v2.pdf",
    )
    assert store["update"]["fileId"] == "existing-id"
    assert store["update"]["body"]["name"] == "renamed-v2.pdf"
    assert store["update"]["kwargs"].get("supportsAllDrives") is True
    assert result["id"] == "existing-id"


@pytest.mark.asyncio
async def test_drive_update_upload_url_returns_session_url(monkeypatch):
    calls = {}
    monkeypatch.setattr("gwsa.sdk.drive.begin_resumable_update",
                        lambda **kw: calls.update(kw) or "https://x/...&upload_id=UPD")
    result = await drive_tools.drive_update_file(
        file_id="f1", upload_url=True, name="v2.pdf", folder_id="fold-9")
    assert result["mode"] == "out_of_band"
    assert result["upload_url"].endswith("upload_id=UPD")
    assert "curl -fL -T" in result["run"]
    assert calls["new_name"] == "v2.pdf" and calls["folder_id"] == "fold-9"


@pytest.mark.asyncio
async def test_drive_update_rename_only_is_a_metadata_update(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_update_file(file_id="f1", name="New name")
    assert store["update"]["body"] == {"name": "New name"}
    assert store["update"]["media"] is None
    assert "addParents" not in store["update"]["kwargs"]
    assert result["name"] == "New name"


@pytest.mark.asyncio
async def test_drive_update_move_only_swaps_parents(patch_drive_service):
    store = patch_drive_service
    result = await drive_tools.drive_update_file(file_id="f1", folder_id="dest")
    kw = store["update"]["kwargs"]
    assert kw["addParents"] == "dest" and kw["removeParents"] == "old-folder"
    assert store["update"]["body"] == {} and store["update"]["media"] is None
    assert result["parents"] == ["dest"]


@pytest.mark.asyncio
async def test_drive_update_rename_move_and_content_in_one_call(patch_drive_service):
    store = patch_drive_service
    await drive_tools.drive_update_file(
        file_id="f1", name="v3.txt", folder_id="dest", content_base64=_b64(b"v3"))
    up = store["update"]
    assert up["body"] == {"name": "v3.txt"} and up["media"] is not None
    assert up["kwargs"]["addParents"] == "dest"


@pytest.mark.asyncio
async def test_drive_update_nothing_to_do_errors():
    result = await drive_tools.drive_update_file(file_id="f1")
    assert "Nothing to update" in result["error"]


@pytest.mark.asyncio
async def test_drive_update_content_and_upload_url_conflict():
    r = await drive_tools.drive_update_file(file_id="f1", content_base64=_b64(b"x"), upload_url=True)
    assert "not both" in r["error"]


@pytest.mark.asyncio
async def test_drive_update_local_missing_file_errors():
    result = await drive_tools.drive_update_file_local(file_id="f1", local_path="/no/such.bin")
    assert "File not found" in result["error"]


# --- security boundary: host-path I/O must stay off the HTTP surface --


def test_network_tools_take_no_server_path():
    """The all-transports tools must not expose a server-side path param —
    that would be an arbitrary server-file read/write over HTTP."""
    assert _transports(drive_tools.drive_create_file) is None      # unannotated = all
    assert "local_path" not in inspect.signature(drive_tools.drive_create_file).parameters
    assert _transports(drive_tools.drive_update_file) is None
    assert "local_path" not in inspect.signature(drive_tools.drive_update_file).parameters
    assert _transports(drive_tools.drive_download) is None
    assert "save_to" not in inspect.signature(drive_tools.drive_download).parameters


def test_host_path_tools_are_stdio_only():
    """The path-reading/-writing tools exist only over stdio."""
    for fn in (
        drive_tools.drive_create_file_local,
        drive_tools.drive_update_file_local,
        drive_tools.drive_download_to_path,
    ):
        assert _transports(fn) == frozenset({"stdio"}), fn.__name__


# --- content types are host-independent -------------------------------


def test_content_types_resolve_without_the_host_mimetypes_table(monkeypatch):
    """Older Pythons and slim images don't know .yaml / .md; gwsa must."""
    import mimetypes
    from gwsa.sdk.content_types import guess_content_type
    monkeypatch.setattr(mimetypes, "guess_type", lambda *a, **k: (None, None))
    assert guess_content_type("a.yaml") == "application/yaml"
    assert guess_content_type("a.YML") == "application/yaml"
    assert guess_content_type("Plan.md") == "text/markdown"
    assert guess_content_type("t.csv") == "text/csv"
    assert guess_content_type("x.unknownext") is None


def test_inline_yaml_upload_and_text_detection_without_host_table(monkeypatch):
    import mimetypes
    from gwsa.sdk.destinations import InlinePayload
    monkeypatch.setattr(mimetypes, "guess_type", lambda *a, **k: (None, None))
    _data, _name, mime = decode_inline_upload(_b64(b"a: 1\n"), name="c.yaml")
    assert mime == "application/yaml"
    p = InlinePayload(name="c.yaml", mime_type="application/octet-stream", size_bytes=5, data=b"a: 1\n")
    assert p.as_text() == ("a: 1\n", "application/yaml")


@pytest.mark.asyncio
async def test_create_file_content_type_overrides_the_name(patch_drive_service):
    store = patch_drive_service
    await drive_tools.drive_create_file(
        content_base64=_b64(b"# x\n"), name="notes", content_type="text/markdown",
        mime_type="application/vnd.google-apps.document",
    )
    assert store["create"]["media"].mimetype() == "text/markdown"


@pytest.mark.asyncio
async def test_update_file_content_type_overrides_the_name(patch_drive_service):
    store = patch_drive_service
    await drive_tools.drive_update_file(
        file_id="f1", content_base64=_b64(b"a,b"), content_type="text/csv")
    assert store["update"]["media"].mimetype() == "text/csv"


@pytest.mark.asyncio
async def test_upload_url_content_type_override(monkeypatch):
    calls = {}
    monkeypatch.setattr("gwsa.sdk.drive.begin_resumable_upload",
                        lambda **kw: calls.update(kw) or "https://x/?upload_id=Q")
    await drive_tools.drive_create_file(name="data", upload_url=True,
                                        content_type="text/csv")
    assert calls["mime_type"] == "text/csv"
