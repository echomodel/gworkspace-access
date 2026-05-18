"""Google Drive MCP tools.

Plain async functions delegating to ``gwsa.sdk.drive``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from gwsa.sdk import drive

logger = logging.getLogger(__name__)


async def drive_list_folder(
    folder_id: Optional[str] = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """List contents of a Google Drive folder.

    Args:
        folder_id: Folder ID to list. Use None for My Drive root.
        max_results: Maximum number of items to return (default 100).

    Returns:
        Dict with a list of files/folders including ``id``, ``name``,
        ``type``, ``mime_type``, ``modified_time``, ``size``. Shortcuts
        (``mime_type: application/vnd.google-apps.shortcut``) also
        include ``target_id`` and ``target_mime_type`` — use
        ``target_id`` with ``drive_download`` to get the actual file.
    """
    try:
        return drive.list_folder(folder_id=folder_id, max_results=max_results)
    except Exception as e:
        logger.error(f"Error listing folder: {e}")
        return {"error": str(e)}


async def drive_create_folder(
    name: str,
    parent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new folder in Google Drive.

    Args:
        name: Name for the new folder.
        parent_id: Parent folder ID. Use None for My Drive root.

    Returns:
        Dict with folder ``id``, ``name``, and ``url``.
    """
    try:
        return drive.create_folder(name=name, parent_id=parent_id)
    except Exception as e:
        logger.error(f"Error creating folder: {e}")
        return {"error": str(e)}


async def drive_upload(
    local_path: str,
    folder_id: Optional[str] = None,
    name: Optional[str] = None,
) -> dict[str, Any]:
    """Upload a local file to Google Drive.

    Args:
        local_path: Absolute path to the local file to upload.
        folder_id: Destination folder ID. Use None for My Drive root.
        name: Name for the file in Drive. Defaults to local filename.

    Returns:
        Dict with file ``id``, ``name``, and ``url``.
    """
    try:
        return drive.upload_file(
            local_path=local_path, folder_id=folder_id, name=name
        )
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return {"error": str(e)}


async def drive_update(
    file_id: str,
    local_path: str,
    name: Optional[str] = None,
) -> dict[str, Any]:
    """Update an existing Drive file's content and optionally rename it.

    Args:
        file_id: Drive file ID to update.
        local_path: Absolute path to the new local file content.
        name: Optional new name for the file.

    Returns:
        Dict with updated file metadata.
    """
    try:
        return drive.update_file(
            file_id=file_id, local_path=local_path, new_name=name
        )
    except Exception as e:
        logger.error(f"Error updating file: {e}")
        return {"error": str(e)}


async def drive_download(file_id: str, save_path: str) -> dict[str, Any]:
    """Download a Drive file to a local path.

    Args:
        file_id: Drive file ID to download.
        save_path: Local path where the file should be saved.

    Returns:
        Dict with ``success`` status, ``saved_to`` path, and
        ``size_bytes``.
    """
    try:
        return drive.download_file(file_id=file_id, save_path=save_path)
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return {"error": str(e)}


async def drive_find_folder(
    path: str,
    drive_id: str = "my_drive",
    folder_id: Optional[str] = None,
) -> dict[str, Any]:
    """Find a folder by navigating a path from a starting location.

    Args:
        path: Folder path with '/' separators (e.g.,
            "Projects/my-project").
        drive_id: Starting drive — "my_drive" (default) or a Shared
            Drive ID. Ignored if ``folder_id`` is provided.
        folder_id: Start from this folder ID instead of a drive root.

    Returns:
        Dict with folder ``id``, ``name``, and ``path``. Returns an
        error envelope if not found or ambiguous.
    """
    try:
        result = drive.find_folder_by_path(
            path, drive=drive_id, folder_id=folder_id
        )
        if result:
            return result
        return {"error": f"Folder not found: {path}"}
    except drive.AmbiguousFolderError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error finding folder: {e}")
        return {"error": str(e)}


async def drive_search_folders(
    name: str,
    match: str = "contains",
    limit: int = 50,
) -> dict[str, Any]:
    """Search for folders by name across all accessible locations.

    One API call. Searches My Drive, Shared Drives, and shared-with-me
    folders.

    Args:
        name: Folder name to search for.
        match: "contains" (default) or "exact" match. Case-insensitive.
        limit: Maximum results to return (default 50).

    Returns:
        Dict with ``folders`` list (each with ``id``, ``name``,
        ``parents``, ``created_time``, ``modified_time``, ``drive_id``)
        and ``count``.
    """
    try:
        if match not in ("contains", "exact"):
            return {"error": f"Invalid match type: {match}. Use 'contains' or 'exact'."}
        results = drive.search_folders(name, match=match, limit=limit)
        return {"folders": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Error searching folders: {e}")
        return {"error": str(e)}
