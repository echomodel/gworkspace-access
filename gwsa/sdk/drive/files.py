"""Google Drive file lifecycle operations (metadata, move, trash).

Per-file primitives that don't belong with upload/download (which carry
bytes) or folders (which navigate the tree). Kept separate so the
file-management surface is easy to find.
"""

from typing import Optional

from .service import get_drive_service


_METADATA_FIELDS = (
    "id, name, mimeType, size, parents, modifiedTime, "
    "webViewLink, shortcutDetails, trashed"
)


def get_metadata(
    file_id: str,
    account: Optional[str] = None,
) -> dict:
    """Fetch metadata for a single Drive file.

    Thin wrapper over ``files.get``. Lets a caller pre-flight a
    download — check size and mimeType before deciding inline vs Drive
    destination, or before reading a large file at all.

    Args:
        file_id: Drive file ID.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with ``id``, ``name``, ``mime_type``, ``size`` (``None``
        or a placeholder for native Google Workspace formats — do not
        treat as a real byte count for Google-native files), ``parents``
        (folder IDs),
        ``modified_time``, ``url`` (webViewLink), ``trashed`` (bool),
        and — for shortcuts — ``target_id`` and ``target_mime_type``.
    """
    service = get_drive_service(account=account)
    file = service.files().get(
        fileId=file_id,
        fields=_METADATA_FIELDS,
        supportsAllDrives=True,
    ).execute()

    result = {
        "id": file.get("id"),
        "name": file.get("name"),
        "mime_type": file.get("mimeType"),
        "size": file.get("size"),
        "parents": file.get("parents", []),
        "modified_time": file.get("modifiedTime"),
        "url": file.get("webViewLink"),
        "trashed": file.get("trashed", False),
    }
    if file.get("mimeType") == "application/vnd.google-apps.shortcut":
        shortcut = file.get("shortcutDetails", {}) or {}
        result["target_id"] = shortcut.get("targetId")
        result["target_mime_type"] = shortcut.get("targetMimeType")
    return result


def move_file(
    file_id: str,
    destination_folder_id: str,
    account: Optional[str] = None,
) -> dict:
    """Move a file to a different folder.

    Drive's REST API does not have a literal "move" — a move is an
    update that adds the new parent and removes the old. This helper
    performs both parent edits in one ``files.update`` call.

    Args:
        file_id: Drive file ID to move.
        destination_folder_id: Folder ID to move into. Use ``'root'`` for
            My Drive root.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with updated file ``id``, ``name``, ``parents`` (list of
        parent folder IDs), and ``url`` (webViewLink).
    """
    service = get_drive_service(account=account)

    # Read current parents so we can remove them in the same update.
    current = service.files().get(
        fileId=file_id,
        fields="parents",
        supportsAllDrives=True,
    ).execute()
    previous_parents = ",".join(current.get("parents", []))

    updated = service.files().update(
        fileId=file_id,
        addParents=destination_folder_id,
        removeParents=previous_parents,
        fields="id, name, parents, webViewLink",
        supportsAllDrives=True,
    ).execute()

    return {
        "id": updated.get("id"),
        "name": updated.get("name"),
        "parents": updated.get("parents", []),
        "url": updated.get("webViewLink"),
    }


def set_properties(
    file_id: str,
    properties: Optional[dict] = None,
    app_properties: Optional[dict] = None,
    account: Optional[str] = None,
) -> dict:
    """Set custom key/value metadata on a Drive file or folder.

    Drive carries two custom-metadata maps on every file:

    - ``properties`` — visible to any app that can access the file.
      A single flat namespace shared across all apps, so **namespace
      your keys** (e.g. ``myapp``) to avoid collisions.
    - ``appProperties`` — private to the OAuth client that wrote them;
      invisible to other clients. Good for secrecy, but **not for
      discovery across different OAuth clients** (e.g. a cloud
      deployment vs. a local CLI), which won't see each other's
      appProperties.

    The update is a **per-key merge**, in one ``files.update`` call:

    - A key present in the map → added or updated.
    - A key whose value is ``None`` → deleted.
    - Keys not mentioned → left untouched (this never clobbers
      properties set by other apps or earlier calls).

    No read-before-write is needed — the merge happens server-side, so
    this is a single round-trip. These tags are API-only: they do not
    appear anywhere in the Drive/Docs/Sheets UI and do not travel with
    a downloaded copy of the file.

    Discover tagged files later with :func:`gwsa.sdk.drive.search_drive`
    using a query like
    ``properties has { key='myapp' and value='expense-tracker' }``.

    Args:
        file_id: Drive file or folder ID.
        properties: Public custom properties to merge. Value ``None``
            for a key deletes that key.
        app_properties: App-private custom properties to merge (same
            null-deletes semantics).
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with ``id``, ``name``, and the resulting ``properties`` and
        ``app_properties`` maps (echoed from the same call — no extra
        read).

    Raises:
        ValueError: if neither ``properties`` nor ``app_properties`` is
            given.
    """
    if properties is None and app_properties is None:
        raise ValueError(
            "set_properties requires properties and/or app_properties"
        )

    body: dict = {}
    if properties is not None:
        body["properties"] = properties
    if app_properties is not None:
        body["appProperties"] = app_properties

    service = get_drive_service(account=account)
    updated = service.files().update(
        fileId=file_id,
        body=body,
        fields="id, name, properties, appProperties",
        supportsAllDrives=True,
    ).execute()

    return {
        "id": updated.get("id"),
        "name": updated.get("name"),
        "properties": updated.get("properties", {}),
        "app_properties": updated.get("appProperties", {}),
    }


def delete_file(
    file_id: str,
    account: Optional[str] = None,
) -> dict:
    """Move a file to Trash.

    Trash semantics are intentional: a user can recover from the Drive
    UI for ~30 days. This matches Drive UI expectations and avoids
    irrecoverable destruction from agent error. A separate primitive
    would be needed for permanent (hard) delete.

    Args:
        file_id: Drive file ID to trash.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with ``file_id`` and ``trashed: True``. Idempotent — calling
        this on an already-trashed file succeeds and returns the same
        shape.
    """
    service = get_drive_service(account=account)

    service.files().update(
        fileId=file_id,
        body={"trashed": True},
        supportsAllDrives=True,
    ).execute()

    return {"file_id": file_id, "trashed": True}
