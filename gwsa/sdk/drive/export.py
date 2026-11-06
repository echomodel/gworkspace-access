"""Export native Google files (Docs, Sheets, Slides, Drawings) to a format.

A native Google file has no stored bytes, so Drive's download
(``files.get?alt=media``, :mod:`gwsa.sdk.drive.download`) refuses it with
HTTP 403 ``fileNotDownloadable``. Its content is reached by **exporting** it
to a concrete format. The rule throughout gwsa: **native files are
exported, uploaded files are downloaded.** Format names (``xlsx``,
``docx``, ``md``, ``pdf``, …) and their export MIME types live in
:mod:`gwsa.sdk.drive.formats`.

How an export runs:

1. ``files.get`` reads the file's ``mimeType`` and ``exportLinks``; the
   format is validated for that type before anything is exported.
2. ``files.export`` streams the content in chunks (as download does).
3. Google caps ``files.export`` at :data:`EXPORT_SIZE_LIMIT_BYTES` (10 MB)
   of exported content and answers a larger export with HTTP 403
   ``exportSizeLimitExceeded``. The export then falls back to an
   authorized GET of the file's ``exportLinks[<mime>]``, which has no such
   cap, streamed to the destination; when the file has no link for that
   format, :class:`ExportLimitExceededError` says so.
4. HTTP 429 (rate limit) and 5xx answers are retried with exponential
   backoff, on both paths.

What an export contains — read this before processing one:

- **Sheets → XLSX/ODS** carry every tab. Cells using a function only
  Google Sheets has, or whose result Google did not save, come out as
  ``=IFERROR(__xludf.DUMMYFUNCTION("<original formula>"),"<last computed
  value>")``. A reader that opens the workbook without evaluating formulas
  sees that formula, not the value (openpyxl: load with
  ``data_only=True`` to read the cached value); some such cells have no
  saved value at all.
- **Hyperlinks in XLSX come in two shapes**: ``=HYPERLINK("url","label")``
  formulas are exported as formulas, and links set in the editor are
  exported as cell hyperlinks. Handle both to recover every URL.
- **Sheets → CSV/TSV export only the first tab** and drop cell
  hyperlinks. For a multi-tab sheet, XLSX or ODS is the only lossless
  choice.
- **Docs → MD/TXT/HTML** include every tab of the document.
"""

from __future__ import annotations

import io
import json
import os
import random
import time
from typing import BinaryIO, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from . import formats
from .download import DEFAULT_DOWNLOAD_CHUNK_SIZE
from .service import get_drive_service

EXPORT_SIZE_LIMIT_BYTES = 10 * 1024 * 1024
"""Google's documented cap on content exported by ``files.export`` (10 MB).

Larger exports are answered with HTTP 403 ``exportSizeLimitExceeded``;
:func:`export_file` and :func:`export_bytes` then fetch the file's
``exportLinks`` entry instead."""

MAX_RETRIES = 5
"""Retries on HTTP 429 and 5xx, with exponential backoff, per request."""

_META_FIELDS = "id, name, mimeType, exportLinks, webViewLink"

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class ExportLimitExceededError(ValueError):
    """The export is over Google's ``files.export`` cap and the file has no
    ``exportLinks`` entry for the format to fall back to."""

    def __init__(self, file_id: str, fmt: str, name: Optional[str] = None):
        self.file_id = file_id
        self.format = fmt
        self.name = name
        super().__init__(
            f"Exporting {name or file_id} as {fmt} is over Google's "
            f"{EXPORT_SIZE_LIMIT_BYTES // (1024 * 1024)} MB export limit, and "
            f"Drive offers no export link for that format on this file. Try "
            f"another format, or split the file."
        )


class ExportTooLargeError(ValueError):
    """The export is larger than the caller's ``max_bytes``.

    ``size_bytes`` is the exported size when known; ``None`` means "larger
    than ``cap_bytes``" (the export was stopped, or Google reported it over
    its own limit, without the full size being read).
    """

    def __init__(self, name: str, cap_bytes: int, size_bytes: Optional[int] = None):
        self.name = name
        self.cap_bytes = cap_bytes
        self.size_bytes = size_bytes
        size = f"{size_bytes} bytes" if size_bytes is not None else f"over {cap_bytes} bytes"
        super().__init__(
            f"Export {name!r} is {size}; the cap for this call is {cap_bytes} bytes."
        )


def get_export_metadata(
    file_id: str,
    fmt: str,
    account: Optional[str] = None,
) -> dict:
    """Validate ``fmt`` for a file and return what an export of it needs.

    Args:
        file_id: The Drive file ID.
        fmt: Format name, e.g. ``"xlsx"`` (see :mod:`gwsa.sdk.drive.formats`).
        account: Optional account selector — name or email.

    Returns:
        Dict with ``name`` (the Drive name), ``file_name`` (with the
        format's extension), ``format``, ``mime_type`` (the export's),
        ``source_mime_type``, ``formats`` (every format for this file),
        ``export_link`` (the file's ``exportLinks`` URL for the format; it
        downloads the export in a browser signed in to the account, or
        ``None``), and ``web_view_link``.

    Raises:
        NotNativeFileError, NoExportFormatsError, UnsupportedExportFormatError:
            see :func:`gwsa.sdk.drive.formats.resolve_export_mime`.
    """
    service = get_drive_service(account=account)
    meta = _read_metadata(service, file_id)
    fmt, export_mime = formats.resolve_export_mime(
        meta.get("mimeType"), fmt, file_id=file_id, name=meta.get("name"))
    return _describe(meta, fmt, export_mime)


def export_file(
    file_id: str,
    save_path: str,
    fmt: str,
    account: Optional[str] = None,
) -> dict:
    """Export a native Google file to a local path.

    Content is streamed to ``<save_path>.part`` and moved to ``save_path``
    only when complete, so a failed export never leaves a truncated file.
    See the module docstring for what XLSX, ODS, CSV and TSV exports
    contain (DUMMYFUNCTION cells, the two hyperlink shapes, CSV covering
    only the first tab) and for the 10 MB ``files.export`` limit, above
    which the file's ``exportLinks`` URL is fetched instead.

    Args:
        file_id: The Drive file ID of a native Google file.
        save_path: Local path to write the export to. Parent directories
            are created.
        fmt: Format name for the file's type, e.g. ``"xlsx"`` / ``"ods"`` /
            ``"csv"`` for a Sheet, ``"docx"`` / ``"md"`` / ``"pdf"`` for a
            Doc, ``"pptx"`` / ``"pdf"`` for Slides.
        account: Optional account selector — name or email. Omit to use the
            user's default account.

    Returns:
        Dict with ``success``, ``file_path``, ``size``, ``name`` (the Drive
        name), ``format``, ``mime_type`` (the export's) and
        ``source_mime_type``.

    Raises:
        NotNativeFileError: The file is an uploaded file; download it.
        UnsupportedExportFormatError: ``fmt`` is not available for this
            type; the error lists the formats that are.
        NoExportFormatsError: A folder, shortcut, Form or Site.
        ExportLimitExceededError: Over Google's export limit with no
            ``exportLinks`` fallback for the format.
    """
    service = get_drive_service(account=account)
    meta = _read_metadata(service, file_id)
    fmt, export_mime = formats.resolve_export_mime(
        meta.get("mimeType"), fmt, file_id=file_id, name=meta.get("name"))

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    part_path = save_path + ".part"
    try:
        with open(part_path, "wb") as fh:
            _export_into(fh, service, file_id, meta, fmt, export_mime, account)
        os.replace(part_path, save_path)
    finally:
        if os.path.exists(part_path):
            os.remove(part_path)

    return {
        "success": True,
        "file_path": save_path,
        "size": os.path.getsize(save_path),
        "name": meta.get("name"),
        "format": fmt,
        "mime_type": export_mime,
        "source_mime_type": meta.get("mimeType"),
    }


def export_bytes(
    file_id: str,
    fmt: str,
    account: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> dict:
    """Export a native Google file into memory and return the bytes.

    The in-memory counterpart to :func:`export_file`, for callers that
    cannot use a local path (MCP tools under HTTP transport). The same
    content notes apply (see the module docstring).

    Args:
        file_id: The Drive file ID of a native Google file.
        fmt: Format name for the file's type (see :func:`export_file`).
        account: Optional account selector — name or email.
        max_bytes: Optional cap. A larger export raises
            :class:`ExportTooLargeError` — the stream is stopped once past
            the cap, so a large export is never held in memory whole.

    Returns:
        Dict with ``data`` (bytes), ``name`` (the Drive name plus the
        format's extension), ``format``, ``mime_type`` (the export's),
        ``source_mime_type`` and ``size_bytes``.

    Raises:
        Everything :func:`export_file` raises, plus
        :class:`ExportTooLargeError` when ``max_bytes`` is exceeded.
    """
    service = get_drive_service(account=account)
    meta = _read_metadata(service, file_id)
    fmt, export_mime = formats.resolve_export_mime(
        meta.get("mimeType"), fmt, file_id=file_id, name=meta.get("name"))
    file_name = formats.export_file_name(meta.get("name"), fmt, f"drive-{file_id[:8]}")

    buffer = io.BytesIO()
    _export_into(buffer, service, file_id, meta, fmt, export_mime, account,
                 max_bytes=max_bytes, display_name=file_name)
    data = buffer.getvalue()
    return {
        "data": data,
        "name": file_name,
        "format": fmt,
        "mime_type": export_mime,
        "source_mime_type": meta.get("mimeType"),
        "size_bytes": len(data),
    }


# --- internals -------------------------------------------------------


def _read_metadata(service, file_id: str) -> dict:
    return service.files().get(
        fileId=file_id, fields=_META_FIELDS, supportsAllDrives=True,
    ).execute(num_retries=MAX_RETRIES)


def _describe(meta: dict, fmt: str, export_mime: str) -> dict:
    source = meta.get("mimeType")
    return {
        "name": meta.get("name"),
        "file_name": formats.export_file_name(meta.get("name"), fmt),
        "format": fmt,
        "mime_type": export_mime,
        "source_mime_type": source,
        "formats": list(formats.export_formats(source)),
        "export_link": (meta.get("exportLinks") or {}).get(export_mime),
        "web_view_link": meta.get("webViewLink"),
    }


def _export_into(
    fh: BinaryIO,
    service,
    file_id: str,
    meta: dict,
    fmt: str,
    export_mime: str,
    account: Optional[str],
    max_bytes: Optional[int] = None,
    display_name: Optional[str] = None,
) -> None:
    """Stream the export into ``fh``: ``files.export``, else ``exportLinks``."""
    name = display_name or meta.get("name") or file_id
    request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    downloader = MediaIoBaseDownload(fh, request, chunksize=DEFAULT_DOWNLOAD_CHUNK_SIZE)
    try:
        done = False
        while not done:
            _status, done = downloader.next_chunk(num_retries=MAX_RETRIES)
            _check_cap(fh, max_bytes, name)
        return
    except HttpError as e:
        if not _is_export_size_limit(e):
            raise

    # Over Google's files.export cap.
    if max_bytes is not None and max_bytes <= EXPORT_SIZE_LIMIT_BYTES:
        raise ExportTooLargeError(name, max_bytes)
    link = (meta.get("exportLinks") or {}).get(export_mime)
    if not link:
        raise ExportLimitExceededError(file_id, fmt, meta.get("name"))
    fh.seek(0)
    fh.truncate(0)
    _stream_export_link(fh, link, account, max_bytes=max_bytes, name=name)


def _check_cap(fh: BinaryIO, max_bytes: Optional[int], name: str) -> None:
    if max_bytes is not None and fh.tell() > max_bytes:
        raise ExportTooLargeError(name, max_bytes, size_bytes=None)


def _is_export_size_limit(e: HttpError) -> bool:
    if getattr(e.resp, "status", None) != 403:
        return False
    try:
        payload = json.loads(e.content.decode("utf-8"))
    except Exception:
        return False
    errors = payload.get("error", {}).get("errors") or []
    return any(err.get("reason") == "exportSizeLimitExceeded" for err in errors)


def _stream_export_link(
    fh: BinaryIO,
    url: str,
    account: Optional[str],
    max_bytes: Optional[int],
    name: str,
) -> None:
    """Authorized, streamed GET of an ``exportLinks`` URL, retrying 429/5xx."""
    for attempt in range(MAX_RETRIES + 1):
        response = _open_export_link(url, account)
        try:
            status = response.status_code
            if status in _RETRY_STATUSES and attempt < MAX_RETRIES:
                _sleep(_backoff_seconds(attempt, response.headers.get("Retry-After")))
                continue
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=DEFAULT_DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    fh.write(chunk)
                    _check_cap(fh, max_bytes, name)
            return
        finally:
            response.close()


def _open_export_link(url: str, account: Optional[str]):
    """Open a streamed GET of ``url`` with the account's credentials."""
    from google.auth.transport.requests import AuthorizedSession

    from ..auth import get_credentials

    creds, _ = get_credentials(account=account)
    return AuthorizedSession(creds).get(url, stream=True, timeout=300)


def _backoff_seconds(attempt: int, retry_after: Optional[str]) -> float:
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return min(2 ** attempt + random.random(), 60.0)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
