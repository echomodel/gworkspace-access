"""Google Drive download operations."""

import io
import os
from typing import Optional

from googleapiclient.http import MediaIoBaseDownload

from .service import get_drive_service


def download_file(
    file_id: str,
    save_path: str,
    show_progress: bool = False
) -> dict:
    """
    Download a file from Google Drive.

    Args:
        file_id: The Drive file ID to download
        save_path: Local path where the file should be saved
        show_progress: If True, print download progress

    Returns:
        Dict with success status, file path, and size in bytes
    """
    service = get_drive_service()

    # Get file metadata first
    file_metadata = service.files().get(
        fileId=file_id,
        fields="name, mimeType, size"
    ).execute()

    # Create request for file content
    request = service.files().get_media(fileId=file_id)

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    # Download to file
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
        "mime_type": file_metadata.get("mimeType")
    }
