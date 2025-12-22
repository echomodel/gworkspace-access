"""Google Drive folder operations."""

from typing import Optional, List, Dict, Any

from .service import get_drive_service


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


def find_folder_by_path(path: str) -> Optional[dict]:
    """
    Find a folder by its path (e.g., 'Projects/my-project/cloud-backups').

    Args:
        path: Folder path with '/' separators

    Returns:
        Dict with folder id and name, or None if not found
    """
    service = get_drive_service()

    parts = [p for p in path.split("/") if p]
    current_parent = "root"

    for part in parts:
        results = service.files().list(
            q=f"'{current_parent}' in parents and name = '{part}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)",
            pageSize=1
        ).execute()

        files = results.get("files", [])
        if not files:
            return None

        current_parent = files[0]["id"]

    return {
        "id": current_parent,
        "name": parts[-1] if parts else "root",
        "path": path
    }
