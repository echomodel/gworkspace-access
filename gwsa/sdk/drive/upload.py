"""Google Drive upload operations."""

import os
import mimetypes
from typing import Optional

from googleapiclient.http import MediaFileUpload

from .service import get_drive_service


def upload_file(
    local_path: str,
    folder_id: Optional[str] = None,
    name: Optional[str] = None
) -> dict:
    """
    Upload a file to Google Drive.

    Args:
        local_path: Path to the local file to upload
        folder_id: Destination folder ID. Use 'root' or None for My Drive root.
        name: Name for the file in Drive. Defaults to local filename.

    Returns:
        Dict with file id, name, and url
    """
    service = get_drive_service()

    # Determine filename
    filename = name or os.path.basename(local_path)

    # Detect mime type
    mime_type, _ = mimetypes.guess_type(local_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    file_metadata = {"name": filename}

    if folder_id and folder_id != "root":
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(
        local_path,
        mimetype=mime_type,
        resumable=True
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink"
    ).execute()

    return {
        "id": file.get("id"),
        "name": file.get("name"),
        "url": file.get("webViewLink")
    }


def update_file(
    file_id: str,
    local_path: str,
    new_name: Optional[str] = None
) -> dict:
    """
    Update an existing file's content and optionally its name.

    Args:
        file_id: The ID of the file to update.
        local_path: Path to the local file content.
        new_name: Optional new name for the file.

    Returns:
        Dict with updated file metadata.
    """
    service = get_drive_service()

    # Detect mime type
    mime_type, _ = mimetypes.guess_type(local_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    file_metadata = {}
    if new_name:
        file_metadata["name"] = new_name

    media = MediaFileUpload(
        local_path,
        mimetype=mime_type,
        resumable=True
    )

    file = service.files().update(
        fileId=file_id,
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink"
    ).execute()

    return {
        "id": file.get("id"),
        "name": file.get("name"),
        "url": file.get("webViewLink")
    }
