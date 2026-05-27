"""Google Drive search operations.

Drive's API has one resource type (``File``) and one search endpoint
(``files.list``). A folder is just a file with
``mimeType = 'application/vnd.google-apps.folder'``; Google Docs,
Sheets, shortcuts, and regular uploads are the same. The query
language documented at
https://developers.google.com/drive/api/guides/search-files lets the
caller discriminate by mimeType, parent, name, full-text, owner,
modified-time, trash state, and more.

This module's :func:`search_drive` is the thin wrapper. Higher-level
helpers (``list_folder``, ``search_folders``, ``find_folder_by_path``)
in :mod:`gwsa.sdk.drive.folders` are pre-shaped queries layered on top
for ergonomics.
"""

from typing import Optional

from .service import get_drive_service


_DEFAULT_FIELDS = (
    "files(id, name, mimeType, modifiedTime, size, parents, "
    "webViewLink, shortcutDetails), nextPageToken"
)


def search_drive(
    query: str,
    max_results: int = 25,
    corpora: str = "user",
    account: Optional[str] = None,
) -> dict:
    """Search Drive via the ``files.list`` endpoint.

    Args:
        query: The Drive query string. Examples:

            - ``"name contains 'invoice' and trashed = false"``
            - ``"mimeType = 'application/vnd.google-apps.folder'"``
            - ``"'<folder_id>' in parents and trashed = false"``
            - ``"fullText contains 'water bill' and "
              "modifiedTime > '2026-01-01'"``

            Full reference:
            https://developers.google.com/drive/api/guides/search-files

        max_results: Maximum number of items per page (default 25).
        corpora: Which corpora to search. One of:

            - ``"user"`` (default) — the caller's My Drive plus files
              shared with the caller.
            - ``"allDrives"`` — My Drive, all Shared Drives the caller
              has access to, and shared-with-me. Use when the target
              file may live in a Shared Drive.
            - ``"domain"`` — files shared to the caller's domain.

        account: Optional account selector — name or email. Omit to
            use the user's default account.

    Returns:
        Dict with ``items`` (list of file records) and
        ``next_page_token``. Each item carries ``id``, ``name``,
        ``mime_type``, ``modified_time``, ``size`` (``None`` or a
        placeholder for native Google Workspace formats — do not treat
        as a real byte count for Google-native files), ``parents`` (list
        of folder IDs),
        ``url`` (webViewLink), and — for shortcuts — ``target_id`` and
        ``target_mime_type``.
    """
    if corpora not in ("user", "allDrives", "domain"):
        raise ValueError(
            f"Unknown corpora value: {corpora!r}. "
            f"Use 'user', 'allDrives', or 'domain'."
        )

    service = get_drive_service(account=account)

    list_kwargs: dict = {
        "q": query,
        "pageSize": max_results,
        "fields": _DEFAULT_FIELDS,
        "corpora": corpora,
    }
    if corpora == "allDrives":
        list_kwargs["includeItemsFromAllDrives"] = True
        list_kwargs["supportsAllDrives"] = True

    result = service.files().list(**list_kwargs).execute()

    items = []
    for file in result.get("files", []):
        item = {
            "id": file.get("id"),
            "name": file.get("name"),
            "mime_type": file.get("mimeType"),
            "modified_time": file.get("modifiedTime"),
            "size": file.get("size"),
            "parents": file.get("parents", []),
            "url": file.get("webViewLink"),
        }
        if file.get("mimeType") == "application/vnd.google-apps.shortcut":
            shortcut = file.get("shortcutDetails", {}) or {}
            item["target_id"] = shortcut.get("targetId")
            item["target_mime_type"] = shortcut.get("targetMimeType")
        items.append(item)

    return {
        "items": items,
        "next_page_token": result.get("nextPageToken"),
    }
