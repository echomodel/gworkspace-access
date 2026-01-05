"""Google Drive folder operations."""

from typing import Optional, List, Dict, Any, Literal

from .service import get_drive_service


class AmbiguousFolderError(Exception):
    """Raised when multiple folders match at the same path level."""
    pass


def list_folder(
    folder_id: Optional[str] = None,
    max_results: int = 100,
    page_token: Optional[str] = None
) -> dict:
    """
    List contents of a Google Drive folder.

    Args:
        folder_id: Folder ID to list. Use 'root' or None for My Drive root.
        max_results: Maximum number of items to return (default 100)
        page_token: Token for pagination

    Returns:
        Dict with:
            - items: List of file/folder info dicts
            - next_page_token: Token for next page (if more results)
    """
    service = get_drive_service()

    # Default to root folder
    parent_id = folder_id or "root"

    results = service.files().list(
        q=f"'{parent_id}' in parents and trashed = false",
        pageSize=max_results,
        pageToken=page_token,
        fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, shortcutDetails)",
        orderBy="folder,name"
    ).execute()

    items = []
    for file in results.get("files", []):
        is_folder = file.get("mimeType") == "application/vnd.google-apps.folder"
        is_shortcut = file.get("mimeType") == "application/vnd.google-apps.shortcut"

        item = {
            "id": file.get("id"),
            "name": file.get("name"),
            "type": "folder" if is_folder else "file",
            "mime_type": file.get("mimeType"),
            "modified_time": file.get("modifiedTime"),
            "size": file.get("size")
        }

        # For shortcuts, include target info for downloading
        if is_shortcut:
            shortcut_details = file.get("shortcutDetails", {})
            item["target_id"] = shortcut_details.get("targetId")
            item["target_mime_type"] = shortcut_details.get("targetMimeType")

        items.append(item)

    return {
        "items": items,
        "next_page_token": results.get("nextPageToken")
    }


def create_folder(
    name: str,
    parent_id: Optional[str] = None
) -> dict:
    """
    Create a new folder in Google Drive.

    Args:
        name: Name for the new folder
        parent_id: Parent folder ID. Use 'root' or None for My Drive root.

    Returns:
        Dict with folder id, name, and url
    """
    service = get_drive_service()

    file_metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder"
    }

    if parent_id and parent_id != "root":
        file_metadata["parents"] = [parent_id]

    folder = service.files().create(
        body=file_metadata,
        fields="id, name"
    ).execute()

    return {
        "id": folder.get("id"),
        "name": folder.get("name"),
        "url": f"https://drive.google.com/drive/folders/{folder.get('id')}"
    }


def find_folder_by_path(
    path: str,
    drive: str = "my_drive",
    folder_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Find a folder by navigating a path from a starting location.

    Args:
        path: Folder path with '/' separators (e.g., 'Projects/my-project')
        drive: Starting drive - "my_drive" or a Shared Drive ID. Ignored if folder_id set.
        folder_id: Start from this folder ID instead of a drive root.

    Returns:
        Dict with folder id, name, and path, or None if not found.

    Raises:
        AmbiguousFolderError: If multiple folders match at the same path level.
    """
    service = get_drive_service()

    parts = [p for p in path.split("/") if p]

    # Determine starting point
    if folder_id:
        current_parent = folder_id
    elif drive == "my_drive":
        current_parent = "root"
    else:
        # Assume drive is a Shared Drive ID
        current_parent = drive

    for part in parts:
        # Escape single quotes in folder names
        escaped_name = part.replace("'", "\\'")
        results = service.files().list(
            q=f"'{current_parent}' in parents and name = '{escaped_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=10  # Get enough to detect ambiguity
        ).execute()

        files = results.get("files", [])
        if not files:
            return None

        if len(files) > 1:
            folder_names = [f"{f['name']} ({f['id']})" for f in files]
            raise AmbiguousFolderError(
                f"Multiple folders named '{part}' at this level: {folder_names}"
            )

        current_parent = files[0]["id"]

    return {
        "id": current_parent,
        "name": parts[-1] if parts else "root",
        "path": path
    }


def search_folders(
    name: str,
    match: Literal["exact", "contains"] = "contains",
    limit: int = 50,
) -> list[dict]:
    """
    Search for folders by name across all accessible locations.

    Single API call. Returns what Drive API provides directly.

    Args:
        name: Folder name to search for.
        match: "contains" (default) or "exact" match.
        limit: Maximum results to return (default 50).

    Returns:
        List of folder dicts with: id, name, parents, created_time,
        modified_time, drive_id (None if in My Drive).
    """
    service = get_drive_service()

    # Build query - escape single quotes
    escaped_name = name.replace("'", "\\'")
    op = "=" if match == "exact" else "contains"
    q = f"mimeType = 'application/vnd.google-apps.folder' and name {op} '{escaped_name}' and trashed = false"

    results = service.files().list(
        q=q,
        corpora="allDrives",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="files(id, name, parents, createdTime, modifiedTime, driveId)",
        pageSize=limit,
    ).execute()

    folders = []
    for f in results.get("files", []):
        folders.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "parents": f.get("parents", []),
            "created_time": f.get("createdTime"),
            "modified_time": f.get("modifiedTime"),
            "drive_id": f.get("driveId"),  # None if My Drive
        })

    return folders
