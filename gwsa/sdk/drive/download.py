"""Google Drive download operations."""

import io
import os
from typing import Optional

from googleapiclient.http import MediaIoBaseDownload

from .service import get_drive_service


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
