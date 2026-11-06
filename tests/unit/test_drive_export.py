"""Unit tests for native-file export (issue #55).

Covers the shared format mapping, the SDK export (``files.export``
streaming, the ``exportLinks`` fallback above Google's export limit, retry
on 429), the native-file guard on download, the CLI commands, the MCP
tools' inline/link/save_to routing, and selecting the SDK user without the
CLI (``use_local_user``).

Sociable style: the mocked boundaries are the Drive API service, the
media downloader (the HTTP transfer) and the export-link GET; the SDK,
CLI and MCP layers run unaltered.
"""

from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError
from mcp.types import BlobResourceContents, TextContent, TextResourceContents
from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile
from gwsa.sdk import drive
from gwsa.sdk.drive import export as export_mod
from gwsa.sdk.drive import formats
from gwsa.sdk.destinations import DEFAULT_INLINE_SIZE_CAP_BYTES

SHEET = formats.SPREADSHEET
DOC = formats.DOCUMENT
SLIDES = formats.PRESENTATION
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --- fixtures and fakes ---------------------------------------------


@pytest.fixture
def user():
    profile = Profile(accounts=[GoogleAccount(
        name="personal", email="alice@example.com",
        token={"client_id": "c", "client_secret": "s", "refresh_token": "r",
               "token_uri": "https://oauth2.googleapis.com/token"})])
    tok = current_user.set(UserRecord(
        email="alice@example.com", profile=profile.model_dump(mode="json")))
    yield
    current_user.reset(tok)


def _service(mime_type, name="Budget", export_links=None):
    svc = MagicMock()
    svc.files.return_value.get.return_value.execute.return_value = {
        "id": "f1", "name": name, "mimeType": mime_type,
        "exportLinks": export_links or {},
        "webViewLink": "https://docs.google.com/x/f1/edit",
        "size": "10",
    }
    return svc


def _size_limit_error():
    resp = MagicMock(status=403, reason="Forbidden")
    content = json.dumps({"error": {"code": 403, "errors": [
        {"reason": "exportSizeLimitExceeded",
         "message": "This file is too large to be exported."}]}}).encode()
    return HttpError(resp, content)


class _Downloader:
    """Stands in for MediaIoBaseDownload: writes ``chunks`` one per call."""

    calls: list = []

    def __init__(self, chunks=None, error=None):
        self.chunks = list(chunks or [])
        self.error = error

    def factory(self):
        def make(fh, request, chunksize):
            self.fh = fh
            return self
        return make

    def next_chunk(self, num_retries=0):
        _Downloader.calls.append(num_retries)
        if self.error is not None:
            raise self.error
        self.fh.write(self.chunks.pop(0))
        return None, not self.chunks


class _LinkResponse:
    def __init__(self, status, chunks=(), headers=None):
        self.status_code = status
        self.chunks = list(chunks)
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


def _export(svc, downloader, fn, *args, **kwargs):
    with patch("gwsa.sdk.drive.export.get_drive_service", return_value=svc), \
            patch("gwsa.sdk.drive.export.MediaIoBaseDownload", downloader.factory()):
        return fn(*args, **kwargs)


# --- the shared format mapping ----------------------------------------


@pytest.mark.parametrize("mime,fmt,expected", [
    (SHEET, "xlsx", XLSX),
    (SHEET, "ods", "application/vnd.oasis.opendocument.spreadsheet"),
    (SHEET, "csv", "text/csv"),
    (SHEET, "tsv", "text/tab-separated-values"),
    (SHEET, "pdf", "application/pdf"),
    (DOC, "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    (DOC, "odt", "application/vnd.oasis.opendocument.text"),
    (DOC, "md", "text/markdown"),
    (DOC, "txt", "text/plain"),
    (DOC, "html", "text/html"),
    (DOC, "epub", "application/epub+zip"),
    (SLIDES, "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    (SLIDES, "odp", "application/vnd.oasis.opendocument.presentation"),
    (SLIDES, "pdf", "application/pdf"),
    (formats.DRAWING, "png", "image/png"),
])
def test_format_maps_to_export_mime_per_type(mime, fmt, expected):
    assert formats.resolve_export_mime(mime, fmt) == (fmt, expected)


def test_aliases_case_and_leading_dot_are_accepted():
    assert formats.resolve_export_mime(DOC, "markdown") == ("md", "text/markdown")
    assert formats.resolve_export_mime(DOC, "text") == ("txt", "text/plain")
    assert formats.resolve_export_mime(SHEET, ".XLSX") == ("xlsx", XLSX)


def test_unsupported_format_lists_the_formats_for_that_type():
    with pytest.raises(formats.UnsupportedExportFormatError) as exc:
        formats.resolve_export_mime(SHEET, "docx")
    assert exc.value.available == ["xlsx", "ods", "csv", "tsv", "pdf", "zip"]
    assert "Google Sheet cannot be exported as 'docx'" in str(exc.value)
    assert "xlsx, ods, csv, tsv, pdf, zip" in str(exc.value)


def test_non_native_file_points_to_download():
    with pytest.raises(formats.NotNativeFileError) as exc:
        formats.resolve_export_mime("application/pdf", "pdf", file_id="f1")
    assert "gwsa drive download f1" in str(exc.value)
    assert "drive_download" in str(exc.value)


def test_folder_has_no_export_formats():
    assert formats.is_native("application/vnd.google-apps.folder")
    with pytest.raises(formats.NoExportFormatsError):
        formats.resolve_export_mime("application/vnd.google-apps.folder", "pdf")


def test_export_links_and_mime_lookup_use_the_same_names():
    links = {XLSX: "https://x/xlsx", "text/csv": "https://x/csv",
             "application/x-unknown": "https://x/u"}
    assert formats.formats_in_export_links(SHEET, links) == {
        "xlsx": "https://x/xlsx", "csv": "https://x/csv"}
    assert formats.format_for_export_mime(SHEET, XLSX) == "xlsx"
    assert formats.format_for_export_mime(SHEET, "image/png") is None


def test_export_file_name_adds_the_extension_once():
    assert formats.export_file_name("Budget", "xlsx") == "Budget.xlsx"
    assert formats.export_file_name("Budget.XLSX", "xlsx") == "Budget.XLSX"
    assert formats.export_file_name(None, "md", "doc") == "doc.md"


def test_every_format_appears_in_the_mcp_and_cli_descriptions():
    from gwsa.cli.drive_commands import export_file as cli_export
    from gwsa.mcp.tools.drive import drive_export

    cli_help = " ".join(p.help or "" for p in cli_export.params)
    for mime, fmts in formats.EXPORT_FORMATS.items():
        for fmt in fmts:
            assert f"``{fmt}``" in drive_export.__doc__, (mime, fmt)
            assert fmt in cli_help, (mime, fmt)


# --- SDK export -------------------------------------------------------


def test_export_bytes_streams_chunks_with_retries(user):
    svc = _service(SHEET)
    _Downloader.calls = []
    result = _export(svc, _Downloader([b"PK", b"\x03\x04rest"]),
                     drive.export_bytes, "f1", "xlsx")
    svc.files.return_value.export_media.assert_called_once_with(
        fileId="f1", mimeType=XLSX)
    assert result["data"] == b"PK\x03\x04rest"
    assert result["name"] == "Budget.xlsx"
    assert result["mime_type"] == XLSX
    assert result["source_mime_type"] == SHEET
    assert result["size_bytes"] == 8
    assert _Downloader.calls == [export_mod.MAX_RETRIES] * 2


def test_export_file_writes_the_file_and_leaves_no_part(user, tmp_path):
    dest = tmp_path / "sub" / "out.xlsx"
    result = _export(_service(SHEET), _Downloader([b"abc", b"def"]),
                     drive.export_file, "f1", str(dest), "xlsx")
    assert dest.read_bytes() == b"abcdef"
    assert result["size"] == 6 and result["format"] == "xlsx"
    assert not (tmp_path / "sub" / "out.xlsx.part").exists()


def test_export_file_failure_leaves_nothing_on_disk(user, tmp_path):
    dest = tmp_path / "out.xlsx"
    boom = HttpError(MagicMock(status=500, reason="err"), b"{}")
    with pytest.raises(HttpError):
        _export(_service(SHEET), _Downloader(error=boom),
                drive.export_file, "f1", str(dest), "xlsx")
    assert list(tmp_path.iterdir()) == []


def test_export_validates_format_before_exporting(user):
    svc = _service(DOC)
    with pytest.raises(drive.UnsupportedExportFormatError) as exc:
        _export(svc, _Downloader([b"x"]), drive.export_bytes, "f1", "xlsx")
    assert "docx" in exc.value.available
    svc.files.return_value.export_media.assert_not_called()


def test_export_of_uploaded_file_is_refused(user):
    svc = _service("application/pdf")
    with pytest.raises(drive.NotNativeFileError):
        _export(svc, _Downloader([b"x"]), drive.export_bytes, "f1", "pdf")
    svc.files.return_value.export_media.assert_not_called()


def test_over_export_limit_falls_back_to_export_link(user, tmp_path):
    svc = _service(SHEET, export_links={XLSX: "https://docs.google.com/export?xlsx"})
    opened = []

    def open_link(url, account):
        opened.append(url)
        return _LinkResponse(200, [b"big-", b"workbook"])

    dest = tmp_path / "big.xlsx"
    with patch("gwsa.sdk.drive.export._open_export_link", side_effect=open_link):
        result = _export(svc, _Downloader(error=_size_limit_error()),
                         drive.export_file, "f1", str(dest), "xlsx")
    assert opened == ["https://docs.google.com/export?xlsx"]
    assert dest.read_bytes() == b"big-workbook"
    assert result["size"] == 12


def test_over_export_limit_without_link_is_a_clear_error(user):
    with pytest.raises(drive.ExportLimitExceededError) as exc:
        _export(_service(SHEET), _Downloader(error=_size_limit_error()),
                drive.export_bytes, "f1", "xlsx")
    assert "10 MB export limit" in str(exc.value)


def test_over_export_limit_with_small_cap_does_not_fetch_the_link(user):
    svc = _service(SHEET, export_links={XLSX: "https://x"})
    with patch("gwsa.sdk.drive.export._open_export_link") as open_link, \
            pytest.raises(drive.ExportTooLargeError):
        _export(svc, _Downloader(error=_size_limit_error()),
                drive.export_bytes, "f1", "xlsx", max_bytes=1000)
    open_link.assert_not_called()


def test_export_link_retries_429_then_succeeds(user):
    svc = _service(SHEET, export_links={XLSX: "https://x"})
    responses = [_LinkResponse(429, headers={"Retry-After": "2"}),
                 _LinkResponse(503), _LinkResponse(200, [b"ok"])]
    sleeps = []
    with patch("gwsa.sdk.drive.export._open_export_link",
               side_effect=lambda url, account: responses.pop(0)), \
            patch("gwsa.sdk.drive.export._sleep", side_effect=sleeps.append):
        result = _export(svc, _Downloader(error=_size_limit_error()),
                         drive.export_bytes, "f1", "xlsx")
    assert result["data"] == b"ok"
    assert len(sleeps) == 2 and sleeps[0] == 2.0


def test_export_link_stream_stops_past_max_bytes(user):
    svc = _service(SHEET, export_links={XLSX: "https://x"})
    resp = _LinkResponse(200, [b"a" * 600, b"b" * 600, b"c" * 600])
    with patch("gwsa.sdk.drive.export._open_export_link", return_value=resp), \
            patch("gwsa.sdk.drive.export.EXPORT_SIZE_LIMIT_BYTES", 100), \
            pytest.raises(drive.ExportTooLargeError):
        _export(svc, _Downloader(error=_size_limit_error()),
                drive.export_bytes, "f1", "xlsx", max_bytes=1000)
    assert resp.closed and resp.chunks  # consumption stopped early


def test_other_http_errors_propagate(user):
    forbidden = HttpError(MagicMock(status=403, reason="Forbidden"),
                          b'{"error": {"errors": [{"reason": "insufficientPermissions"}]}}')
    with pytest.raises(HttpError):
        _export(_service(SHEET), _Downloader(error=forbidden),
                drive.export_bytes, "f1", "xlsx")


# --- download refuses native files ------------------------------------


@pytest.mark.parametrize("fn", ["download_bytes", "download_file"])
def test_download_of_native_file_hints_at_export(user, tmp_path, fn):
    svc = _service(SHEET)
    args = ("f1",) if fn == "download_bytes" else ("f1", str(tmp_path / "x"))
    with patch("gwsa.sdk.drive.download.get_drive_service", return_value=svc), \
            pytest.raises(drive.NativeFileDownloadError) as exc:
        getattr(drive, fn)(*args)
    svc.files.return_value.get_media.assert_not_called()
    msg = str(exc.value)
    assert "gwsa drive export f1 PATH --format xlsx" in msg
    assert "drive_export" in msg and "xlsx, ods, csv" in msg
    assert exc.value.available[0] == "xlsx"


# --- CLI --------------------------------------------------------------


def _cli(args, svc_module, svc):
    from gwsa.cli.__main__ import gwsa

    with patch("gwsa.sdk.auth.use_local_user", return_value="local"), \
            patch(f"gwsa.sdk.drive.{svc_module}.get_drive_service", return_value=svc):
        return CliRunner().invoke(gwsa, args)


def test_cli_download_of_native_file_fails_with_hint(user, tmp_path):
    result = _cli(["drive", "download", "f1", str(tmp_path / "out")],
                  "download", _service(SHEET))
    assert result.exit_code == 1
    assert "gwsa drive export f1 PATH --format xlsx" in result.output


def test_cli_export_writes_file(user, tmp_path):
    dest = tmp_path / "out.md"
    with patch("gwsa.sdk.drive.export.MediaIoBaseDownload",
               _Downloader([b"# Title\n"]).factory()):
        result = _cli(["drive", "export", "f1", str(dest), "--format", "markdown"],
                      "export", _service(DOC))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["format"] == "md"
    assert dest.read_bytes() == b"# Title\n"


def test_cli_export_unsupported_format_lists_formats(user, tmp_path):
    result = _cli(["drive", "export", "f1", str(tmp_path / "o"), "--format", "xlsx"],
                  "export", _service(SLIDES))
    assert result.exit_code == 1
    assert "pptx, odp, pdf, txt" in result.output


# --- MCP tools --------------------------------------------------------


def _mcp_export(svc, downloader, **kwargs):
    from gwsa.mcp.tools.drive import drive_export

    with patch("gwsa.sdk.drive.export.get_drive_service", return_value=svc), \
            patch("gwsa.sdk.drive.export.MediaIoBaseDownload", downloader.factory()):
        return asyncio.run(drive_export(**kwargs))


def test_mcp_export_small_text_format_comes_back_as_text(user):
    blocks = _mcp_export(_service(SHEET), _Downloader([b"a,b\n1,2\n"]),
                         file_id="f1", format="csv")
    summary, embedded = blocks
    assert isinstance(summary, TextContent)
    assert json.loads(summary.text)["name"] == "Budget.csv"
    assert isinstance(embedded.resource, TextResourceContents)
    assert embedded.resource.text == "a,b\n1,2\n"
    assert embedded.resource.mimeType == "text/csv"


def test_mcp_export_small_binary_format_is_base64(user):
    _, embedded = _mcp_export(_service(SHEET), _Downloader([b"PK\x03\x04"]),
                              file_id="f1", format="xlsx")
    assert isinstance(embedded.resource, BlobResourceContents)
    assert base64.b64decode(embedded.resource.blob) == b"PK\x03\x04"


def test_mcp_export_large_returns_export_link(user):
    svc = _service(SHEET, export_links={XLSX: "https://docs.google.com/export?xlsx"})
    big = b"x" * (DEFAULT_INLINE_SIZE_CAP_BYTES + 1)
    result = _mcp_export(svc, _Downloader([big]), file_id="f1", format="xlsx")
    assert result["mode"] == "link"
    assert result["url"] == "https://docs.google.com/export?xlsx"
    assert result["name"] == "Budget.xlsx" and result["format"] == "xlsx"


def test_mcp_export_over_google_limit_returns_link_without_fetching(user):
    svc = _service(SHEET, export_links={XLSX: "https://x/xlsx"})
    with patch("gwsa.sdk.drive.export._open_export_link") as open_link:
        result = _mcp_export(svc, _Downloader(error=_size_limit_error()),
                             file_id="f1", format="xlsx")
    open_link.assert_not_called()
    assert result["mode"] == "link" and result["url"] == "https://x/xlsx"


def test_mcp_export_unsupported_format_envelope(user):
    result = _mcp_export(_service(DOC), _Downloader([b"x"]),
                         file_id="f1", format="xlsx")
    assert result["success"] is False
    assert result["export_formats"][0] == "docx"


def test_mcp_export_uploaded_file_envelope(user):
    result = _mcp_export(_service("application/pdf"), _Downloader([b"x"]),
                         file_id="f1", format="pdf")
    assert result["success"] is False and result["native_file"] is False
    assert "drive_download" in result["error"]


def test_mcp_export_to_path_saves(user, tmp_path):
    from gwsa.mcp.tools.drive import drive_export_to_path

    dest = tmp_path / "deck.pptx"
    with patch("gwsa.sdk.drive.export.get_drive_service", return_value=_service(SLIDES)), \
            patch("gwsa.sdk.drive.export.MediaIoBaseDownload",
                  _Downloader([b"PPTX"]).factory()):
        result = asyncio.run(drive_export_to_path(
            file_id="f1", format="pptx", save_to=str(dest)))
    assert result["mode"] == "saved" and result["path"] == str(dest)
    assert dest.read_bytes() == b"PPTX"


def test_mcp_export_to_path_is_stdio_only():
    from gwsa import app
    from mcp_app.app import _discover_tools

    http = {f.__name__ for f in _discover_tools(app._discovered_modules, "http")}
    stdio = {f.__name__ for f in _discover_tools(app._discovered_modules, "stdio")}
    assert "drive_export" in http and "drive_export" in stdio
    assert "drive_export_to_path" in stdio and "drive_export_to_path" not in http


def test_mcp_download_of_native_file_points_to_export(user):
    from gwsa.mcp.tools.drive import drive_download

    meta = {"name": "Budget", "mime_type": SHEET, "size": None,
            "web_content_link": None, "web_view_link": "https://x"}
    with patch("gwsa.sdk.drive.get_download_metadata", return_value=meta), \
            patch("gwsa.sdk.drive.download_bytes") as dl:
        result = asyncio.run(drive_download(file_id="f1"))
    dl.assert_not_called()
    assert result["native_file"] is True
    assert result["export_formats"][:2] == ["xlsx", "ods"]
    assert "drive_export" in result["error"]


def test_mcp_download_to_path_of_native_file_points_to_export(user, tmp_path):
    from gwsa.mcp.tools.drive import drive_download_to_path

    with patch("gwsa.sdk.drive.download.get_drive_service", return_value=_service(DOC)):
        result = asyncio.run(drive_download_to_path(
            file_id="f1", save_to=str(tmp_path / "x")))
    assert result["native_file"] is True and "docx" in result["export_formats"]


# --- selecting the SDK user without the CLI ---------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An isolated local user store, filled through gwsa-admin."""
    from gwsa import app

    for var, sub in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                     ("XDG_DATA_HOME", "data"), ("APP_USERS_PATH", "users")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(var, str(tmp_path / sub))
    token = tmp_path / "token.json"
    token.write_text(json.dumps({
        "client_id": "c", "client_secret": "s", "refresh_token": "r",
        "token_uri": "https://oauth2.googleapis.com/token"}))

    def add(user_key: str):
        if user_key != "local":
            result = CliRunner().invoke(app.admin_cli, ["users", "add", user_key])
            assert result.exit_code == 0, result.output
        result = CliRunner().invoke(app.admin_cli, [
            "accounts", "add", "personal", "--email", "alice@example.com",
            f"--token=@{token}", "--user", user_key])
        assert result.exit_code == 0, result.output

    result = CliRunner().invoke(app.admin_cli, ["connect", "local"])
    assert result.exit_code == 0, result.output
    tok = current_user.set(None)
    yield add
    current_user.reset(tok)


def test_use_local_user_selects_the_only_user(store):
    from gwsa.sdk.auth import get_google_account_creds, use_local_user

    store("local")
    assert use_local_user() == "local"
    _creds, account = get_google_account_creds()
    assert account.email == "alice@example.com"


def test_use_local_user_prefers_local_among_several(store):
    from gwsa.sdk.auth import use_local_user

    store("local")
    store("someone@example.com")
    assert use_local_user() == "local"
    assert use_local_user("someone@example.com") == "someone@example.com"
    assert current_user.get().email == "someone@example.com"


def test_use_local_user_errors(store):
    from gwsa.sdk.auth import LocalUserError, use_local_user

    with pytest.raises(LocalUserError, match="No users in the local store"):
        use_local_user()
    store("a@example.com")
    store("b@example.com")
    with pytest.raises(LocalUserError, match="Multiple users"):
        use_local_user()
    with pytest.raises(LocalUserError, match="not found"):
        use_local_user("c@example.com")


def test_use_local_user_works_inside_a_running_event_loop(store):
    from gwsa.sdk.auth import use_local_user

    store("local")

    async def main():
        return use_local_user()

    assert asyncio.run(main()) == "local"


def test_sdk_without_a_user_names_use_local_user(store):
    from gwsa.sdk.auth import get_credentials

    with pytest.raises(LookupError, match="use_local_user"):
        get_credentials()
