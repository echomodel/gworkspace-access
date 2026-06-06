"""Google Drive download operations."""

import io
import os
from typing import Iterator, Optional

from googleapiclient.http import MediaIoBaseDownload

from .service import get_drive_service

DEFAULT_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
"""Chunk size for streaming downloads (1 MiB).

Bounds peak memory per in-flight request on the HTTP data plane: the
server holds at most ~one chunk at a time rather than the whole file.
Large enough to keep per-chunk API overhead low, small enough that many
concurrent transfers don't blow the container's memory."""


def _fetch_bytes(service, file_id: str) -> tuple[bytes, dict]:
    """Fetch a Drive file's bytes plus its metadata.

    Shared by :func:`download_file` (writes to disk) and
    :func:`download_bytes` (returns in-memory) so the API call lives in
    one place.
    """
    file_metadata = service.files().get(
        fileId=file_id,
        fields="name, mimeType, size",
    ).execute()

    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue(), file_metadata


def download_file(
    file_id: str,
    save_path: str,
    show_progress: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Download a Drive file to a local filesystem path.

    Used by the gwsa CLI and any other caller that has a real local
    filesystem to write to. For tools that need to keep the bytes in
    memory (e.g. MCP tools that must work under HTTP transport), use
    :func:`download_bytes` instead.

    Args:
        file_id: The Drive file ID to download
        save_path: Local path where the file should be saved
        show_progress: If True, print download progress
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with success status, file path, and size in bytes.
    """
    service = get_drive_service(account=account)

    file_metadata = service.files().get(
        fileId=file_id,
        fields="name, mimeType, size"
    ).execute()

    request = service.files().get_media(fileId=file_id)

    # Ensure parent directory exists.
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    with open(save_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if show_progress and status:
                print(f"Download progress: {int(status.progress() * 100)}%")

    file_size = os.path.getsize(save_path)

    return {
        "success": True,
        "file_path": save_path,
        "size": file_size,
        "name": file_metadata.get("name"),
        "mime_type": file_metadata.get("mimeType"),
    }


def get_download_metadata(
    file_id: str,
    account: Optional[str] = None,
    service=None,
) -> dict:
    """Fetch the metadata a streaming download needs before sending bytes.

    The HTTP data plane must set response headers (content type, file
    name, length) *before* it starts streaming the body, so it reads the
    metadata in one cheap call up front and then streams via
    :func:`iter_download_chunks`.

    Args:
        file_id: The Drive file ID.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with ``name``, ``mime_type``, ``size`` (the Drive-reported
        byte count as a string, or ``None`` if Drive doesn't report it),
        ``web_content_link`` (a direct-download URL for binary files, or
        ``None`` for native Google files), and ``web_view_link`` (the
        in-Drive view URL). The links require the caller's browser to be
        signed in to the owning Google account — they are not public.
    """
    service = get_drive_service(account=account)
    meta = service.files().get(
        fileId=file_id,
        fields="name, mimeType, size, webContentLink, webViewLink",
    ).execute()
    return {
        "name": meta.get("name"),
        "mime_type": meta.get("mimeType"),
        "size": meta.get("size"),
        "web_content_link": meta.get("webContentLink"),
        "web_view_link": meta.get("webViewLink"),
    }


def iter_download_chunks(
    file_id: str,
    account: Optional[str] = None,
    chunk_size: int = DEFAULT_DOWNLOAD_CHUNK_SIZE,
) -> Iterator[bytes]:
    """Yield a Drive file's content in constant-memory chunks.

    The streaming counterpart to :func:`download_bytes` (whole file in
    memory) and :func:`download_file` (whole file to disk). Instead of
    buffering, it yields ~``chunk_size`` byte blocks so the HTTP data
    plane can stream a file of any size with bounded peak memory — the
    generator holds at most one chunk at a time.

    Pair with :func:`get_download_metadata` to set response headers
    before iterating.

    Args:
        file_id: The Drive file ID to stream.
        account: Optional account selector — name or email. Omit to use
            the user's default account.
        chunk_size: Bytes to request per Drive API round trip.

    Yields:
        Successive ``bytes`` blocks of the file content, in order.
    """
    service = get_drive_service(account=account)
    request = service.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request, chunksize=chunk_size)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
        data = buffer.getvalue()
        if data:
            yield data
        # Reset the buffer so the next chunk starts empty — this is what
        # keeps memory bounded to one chunk rather than the whole file.
        buffer.seek(0)
        buffer.truncate(0)


def download_bytes(
    file_id: str,
    account: Optional[str] = None,
) -> dict:
    """Download a Drive file into memory and return the bytes.

    The in-memory counterpart to :func:`download_file`. Used by tools
    that must work under HTTP transport (where saving to the server's
    filesystem is useless to the agent) and by callers that intend to
    pass the bytes directly into another tool.

    Args:
        file_id: The Drive file ID to download.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with ``data`` (bytes), ``name``, ``mime_type``, and
        ``size_bytes``.
    """
    service = get_drive_service(account=account)
    data, file_metadata = _fetch_bytes(service, file_id)
    return {
        "data": data,
        "name": file_metadata.get("name"),
        "mime_type": file_metadata.get("mimeType"),
        "size_bytes": len(data),
    }
