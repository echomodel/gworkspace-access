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
        for native Google Workspace formats), ``parents`` (folder IDs),
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
