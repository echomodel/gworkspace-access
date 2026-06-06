"""Google Drive upload operations."""

import io
import json
import mimetypes
import os
from typing import Optional

import httpx
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from ..auth import get_credentials
from .service import get_drive_service

# Resumable-upload initiation endpoints. The session URI these return is
# self-authorizing — the data PUT carries no Authorization header
# (verified live against the Drive API) — so an agent can `curl -T` the
# bytes straight to Google, out-of-band of this server.
_RESUMABLE_CREATE = (
    "https://www.googleapis.com/upload/drive/v3/files"
    "?uploadType=resumable&supportsAllDrives=true"
)
_RESUMABLE_UPDATE = (
    "https://www.googleapis.com/upload/drive/v3/files/{file_id}"
    "?uploadType=resumable&supportsAllDrives=true"
)


def _fresh_access_token(account: Optional[str]) -> str:
    """Return a valid access token for ``account`` (refreshing if needed)."""
    creds, _ = get_credentials(account=account)
    if not creds.valid:
        from google.auth.transport.requests import Request

        creds.refresh(Request())
    return creds.token


def _initiate_resumable(
    url: str, method: str, metadata: dict, mime_type: str,
    size: Optional[int], account: Optional[str],
) -> str:
    token = _fresh_access_token(account)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": mime_type,
    }
    if size is not None:
        headers["X-Upload-Content-Length"] = str(size)
    resp = httpx.request(
        method, url, headers=headers, content=json.dumps(metadata), timeout=30
    )
    resp.raise_for_status()
    session_uri = resp.headers.get("location")
    if not session_uri:
        raise RuntimeError(
            "Drive did not return a resumable upload session URI "
            f"(status {resp.status_code})."
        )
    return session_uri


def begin_resumable_upload(
    name: str,
    mime_type: str = "application/octet-stream",
    folder_id: Optional[str] = None,
    size: Optional[int] = None,
    account: Optional[str] = None,
) -> str:
    """Start a resumable session to create a NEW file; return the session URI.

    The control-plane half of the direct-to-Google upload: this server
    (holding the credential) initiates the session, then the caller PUTs
    the bytes directly to the returned URI with **no Authorization
    header** — so the bytes never traverse this server, there is no
    request-size cap, and no credential reaches the agent. The session
    URI is valid for ~1 week.

    Args:
        name: File name to create in Drive.
        mime_type: Content type the caller will upload.
        folder_id: Destination folder ID. ``None``/``"root"`` = My Drive.
        size: Total byte count, if known (sent as
            ``X-Upload-Content-Length`` to let Drive validate).
        account: Optional account selector — name or email.

    Returns:
        The resumable session URI to PUT the bytes to.
    """
    metadata: dict = {"name": name}
    if folder_id and folder_id != "root":
        metadata["parents"] = [folder_id]
    return _initiate_resumable(
        _RESUMABLE_CREATE, "POST", metadata, mime_type, size, account
    )


def begin_resumable_update(
    file_id: str,
    mime_type: str = "application/octet-stream",
    new_name: Optional[str] = None,
    size: Optional[int] = None,
    account: Optional[str] = None,
) -> str:
    """Start a resumable session to replace an EXISTING file's content.

    The update counterpart to :func:`begin_resumable_upload` — same
    self-authorizing session-URI contract, but it targets an existing
    ``file_id`` (so revisions stack on that file).

    Args:
        file_id: The Drive file whose content will be replaced.
        mime_type: Content type the caller will upload.
        new_name: Optional new name for the file.
        size: Total byte count, if known.
        account: Optional account selector — name or email.

    Returns:
        The resumable session URI to PUT the new bytes to.
    """
    metadata: dict = {}
    if new_name:
        metadata["name"] = new_name
    return _initiate_resumable(
        _RESUMABLE_UPDATE.format(file_id=file_id),
        "PATCH", metadata, mime_type, size, account,
    )


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
