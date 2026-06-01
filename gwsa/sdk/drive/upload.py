"""Google Drive upload operations."""

import io
import mimetypes
import os
from typing import Optional

from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from .service import get_drive_service


def upload_file(
    local_path: str,
    folder_id: Optional[str] = None,
    name: Optional[str] = None,
    keep_revision_forever: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Upload a file to Google Drive.

    Args:
        local_path: Path to the local file to upload
        folder_id: Destination folder ID. Use 'root' or None for My Drive root.
        name: Name for the file in Drive. Defaults to local filename.
        keep_revision_forever: Pin the resulting (initial) revision with
            ``keepForever`` so it survives Drive's auto-pruning. Atomic —
            no separate ``keep_revision`` call needed. Only meaningful for
            binary (non-native) content.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with file id, name, url, and ``keep_revision_forever``.
    """
    service = get_drive_service(account=account)

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
        fields="id, name, webViewLink",
        supportsAllDrives=True,
        keepRevisionForever=keep_revision_forever,
    ).execute()

    return {
        "id": file.get("id"),
        "name": file.get("name"),
        "url": file.get("webViewLink"),
        "keep_revision_forever": keep_revision_forever,
    }


def upload_bytes(
    data: bytes,
    name: str,
    mime_type: str = "application/octet-stream",
    folder_id: Optional[str] = None,
    keep_revision_forever: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Upload raw bytes as a new file in Google Drive.

    The in-memory counterpart to :func:`upload_file`. Used by tools that
    have bytes already in hand (e.g. an email attachment downloaded via
    the Gmail API) and want to land them in Drive without a filesystem
    round-trip — required for hosted MCP deployments where the server
    has no useful local filesystem from the agent's perspective.

    Args:
        data: Raw bytes to upload.
        name: File name to use in Drive.
        mime_type: MIME type of the content. Defaults to
            ``application/octet-stream``.
        folder_id: Destination folder ID. Use ``'root'`` or ``None`` for
            My Drive root.
        keep_revision_forever: Pin the resulting (initial) revision with
            ``keepForever`` so it survives Drive's auto-pruning. Atomic.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with file ``id``, ``name``, ``url`` (webViewLink), and
        ``keep_revision_forever``.
    """
    service = get_drive_service(account=account)

    file_metadata: dict = {"name": name}
    if folder_id and folder_id != "root":
        file_metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(
        io.BytesIO(data),
        mimetype=mime_type,
        resumable=True,
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
        supportsAllDrives=True,
        keepRevisionForever=keep_revision_forever,
    ).execute()

    return {
        "id": file.get("id"),
        "name": file.get("name"),
        "url": file.get("webViewLink"),
        "keep_revision_forever": keep_revision_forever,
    }


def update_bytes(
    file_id: str,
    data: bytes,
    mime_type: str = "application/octet-stream",
    new_name: Optional[str] = None,
    keep_revision_forever: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Update an existing file's content from raw bytes.

    The in-memory counterpart to :func:`update_file`. Used by the MCP
    layer when the new content arrives inline (base64) rather than as a
    server-readable path — required under HTTP transport where the
    server cannot read the agent's filesystem.

    Args:
        file_id: The ID of the file to update.
        data: Raw bytes of the new content.
        mime_type: MIME type of the content. Defaults to
            ``application/octet-stream``.
        new_name: Optional new name for the file.
        keep_revision_forever: Pin the resulting (new head) revision with
            ``keepForever`` in the same call, so this version survives
            Drive's auto-pruning. Atomic — no separate ``keep_revision``
            call needed.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with updated file ``id``, ``name``, ``url``, and
        ``keep_revision_forever``.
    """
    service = get_drive_service(account=account)

    file_metadata: dict = {}
    if new_name:
        file_metadata["name"] = new_name

    media = MediaIoBaseUpload(
        io.BytesIO(data),
        mimetype=mime_type,
        resumable=True,
    )

    file = service.files().update(
        fileId=file_id,
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink",
        supportsAllDrives=True,
        keepRevisionForever=keep_revision_forever,
    ).execute()

    return {
        "id": file.get("id"),
        "name": file.get("name"),
        "url": file.get("webViewLink"),
        "keep_revision_forever": keep_revision_forever,
    }


def update_file(
    file_id: str,
    local_path: str,
    new_name: Optional[str] = None,
    keep_revision_forever: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Update an existing file's content and optionally its name.

    Args:
        file_id: The ID of the file to update.
        local_path: Path to the local file content.
        new_name: Optional new name for the file.
        keep_revision_forever: Pin the resulting (new head) revision with
            ``keepForever`` in the same call, so this version survives
            Drive's auto-pruning. Atomic — no separate ``keep_revision``
            call needed.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with updated file metadata plus ``keep_revision_forever``.
    """
    service = get_drive_service(account=account)

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
        fields="id, name, webViewLink",
        supportsAllDrives=True,
        keepRevisionForever=keep_revision_forever,
    ).execute()

    return {
        "id": file.get("id"),
        "name": file.get("name"),
        "url": file.get("webViewLink"),
        "keep_revision_forever": keep_revision_forever,
    }
