"""Google Drive MCP tools.

Plain async functions delegating to ``gwsa.sdk.drive``.

Every tool accepts an optional ``account`` parameter: pass either
the account ``name`` (e.g. ``"work"``) or its Google ``email`` (e.g.
``"alice@example.com"``) to operate as a specific account on the
current user's profile. Omit to use the user's ``default_account``
(or the sole account if only one is configured). Use the
``list_google_accounts`` tool to discover available account names
and emails.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from gwsa.sdk import drive
from gwsa.sdk.destinations import (
    DEFAULT_INLINE_SIZE_CAP_BYTES,
    InlineDestination,
    InlinePayload,
    InlineTooLargeError,
    materialize,
)
from gwsa.sdk.sources import (
    InlineSourceTooLargeError,
    InvalidInlineSourceError,
    LocalPathSource,
    Source,
    resolve_source,
)
from gwsa.mcp.content import ContentBlock, inline_payload_to_blocks

logger = logging.getLogger(__name__)


async def drive_list_folder(
    folder_id: Optional[str] = None,
    max_results: int = 100,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List the contents of a Drive folder.

    Returns everything directly inside the folder — subfolders, regular
    files, native Google Workspace files (Docs, Sheets, Slides),
    shortcuts — mirroring how the Drive UI renders a folder. Convenience
    over ``drive_search`` for the highest-frequency Drive operation;
    equivalent to ``drive_search(q="'<folder_id>' in parents and trashed
    = false")``.

    Args:
        folder_id: Folder ID to list. Use None for My Drive root.
        max_results: Maximum number of items to return (default 100).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``items`` (list) and ``next_page_token``. Each item
        carries ``id``, ``name``, ``type`` (``"folder"`` or ``"file"``
        — derived from ``mime_type``), ``mime_type``, ``modified_time``,
        and ``size``.

        Notes on ``size``: native Google Workspace formats (Docs /
        Sheets / Slides / Forms etc.) have no meaningful raw byte count;
        Drive's API returns either ``None`` or a small placeholder value
        for these, so do not treat the field as a real byte count for
        Google-native files. Folders behave the same way.

        Shortcuts have ``mime_type =
        "application/vnd.google-apps.shortcut"`` and additional
        ``target_id`` + ``target_mime_type`` fields — pass ``target_id``
        to ``drive_download`` or ``drive_get_metadata`` to operate on
        the underlying file.
    """
    try:
        return drive.list_folder(
            folder_id=folder_id, max_results=max_results, account=account
        )
    except Exception as e:
        logger.error(f"Error listing folder: {e}")
        return {"error": str(e)}


async def drive_create_folder(
    name: str,
    parent_id: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new folder in Google Drive.

    Args:
        name: Name for the new folder.
        parent_id: Parent folder ID. Use None for My Drive root.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with folder ``id``, ``name``, and ``url``.
    """
    try:
        return drive.create_folder(name=name, parent_id=parent_id, account=account)
    except Exception as e:
        logger.error(f"Error creating folder: {e}")
        return {"error": str(e)}


async def drive_upload(
    source: Source,
    folder_id: Optional[str] = None,
    name: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Upload a file to Google Drive.

    The ``source`` parameter is a discriminated union; pass one of:

    - ``{"kind": "inline", "data_base64": "<b64>", "name": "<name>",
      "mime_type": "<type>"}`` — carry the bytes inline. Works under
      ANY transport (stdio or HTTP) because the content travels in the
      request body. Recommended default; required when the MCP server
      and the agent do not share a filesystem (hosted/HTTP). Subject to
      a size cap (see ``max_size_bytes`` on the inline source).
    - ``{"kind": "path", "path": "/abs/path"}`` — read the bytes from a
      path on the SERVER's filesystem. Only correct under stdio
      transport, where the server runs on the agent's machine. Under
      HTTP this fails because the server can't see the agent's files.

    Args:
        source: Where the bytes come from. See above.
        folder_id: Destination folder ID. Use None for My Drive root.
        name: Name for the file in Drive. Overrides the source's own
            name; falls back to the source name, then the path basename.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with file ``id``, ``name``, and ``url``.
    """
    try:
        data, src_name, mime_type = resolve_source(source)
        final_name = name or src_name
        if not final_name:
            return {
                "error": (
                    "No file name available. Provide 'name', or a "
                    "'name' on the inline source."
                )
            }
        return drive.upload_bytes(
            data=data,
            name=final_name,
            mime_type=mime_type,
            folder_id=folder_id,
            account=account,
        )
    except InlineSourceTooLargeError as e:
        return {
            "success": False,
            "error": str(e),
            "size_bytes": e.size_bytes,
            "cap_bytes": e.cap_bytes,
            "hint": (
                "Upload via a server-readable path under stdio, or raise "
                "max_size_bytes on the inline source if the client allows "
                "larger request bodies."
            ),
        }
    except (InvalidInlineSourceError, FileNotFoundError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return {"error": str(e)}


async def drive_update(
    file_id: str,
    source: Source,
    name: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Update an existing Drive file's content and optionally rename it.

    The ``source`` parameter is the same discriminated union as
    ``drive_upload`` — pass an inline source (works under any transport)
    or a server-local path source (stdio only). See ``drive_upload`` for
    the full shape.

    Args:
        file_id: Drive file ID to update.
        source: Where the new content comes from (inline or path).
        name: Optional new name for the file.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with updated file ``id``, ``name``, and ``url``.
    """
    try:
        data, _src_name, mime_type = resolve_source(source)
        return drive.update_bytes(
            file_id=file_id,
            data=data,
            mime_type=mime_type,
            new_name=name,
            account=account,
        )
    except InlineSourceTooLargeError as e:
        return {
            "success": False,
            "error": str(e),
            "size_bytes": e.size_bytes,
            "cap_bytes": e.cap_bytes,
            "hint": (
                "Update via a server-readable path under stdio, or raise "
                "max_size_bytes on the inline source if the client allows "
                "larger request bodies."
            ),
        }
    except (InvalidInlineSourceError, FileNotFoundError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error updating file: {e}")
        return {"error": str(e)}


async def drive_download(
    file_id: str,
    max_size_bytes: Optional[int] = None,
    account: Optional[str] = None,
) -> list[ContentBlock] | dict[str, Any]:
    """Fetch a Drive file's contents inline as an MCP EmbeddedResource.

    Returns ``[TextContent summary, EmbeddedResource]``. The bytes are
    base64-encoded in the embedded resource so the agent receives them
    directly under any transport (stdio, HTTP, anything else).

    For larger files or files the agent doesn't need to consume
    immediately, leave the file in Drive and operate on it via
    ``drive_move`` / ``drive_delete`` / sharing — Drive is already the
    canonical store.

    Args:
        file_id: Drive file ID to fetch.
        max_size_bytes: Override the default inline size cap on raw
            bytes (default 60,000 — sized so base64 + envelope fits
            inside Claude Code's ~25K-token tool-response budget; see
            :data:`gwsa.sdk.destinations.DEFAULT_INLINE_SIZE_CAP_BYTES`
            for the math). Files larger than the cap return an error
            envelope rather than risking client truncation. Use
            ``drive_get_metadata`` first to check ``size`` before
            calling.
        account: Optional account selector (name or email). Omit to
            use the user's default account.
    """
    try:
        fetched = drive.download_bytes(file_id=file_id, account=account)
        result = materialize(
            fetched["data"],
            name=fetched["name"] or f"drive-{file_id[:8]}",
            mime_type=fetched["mime_type"] or "application/octet-stream",
            destination=InlineDestination(max_size_bytes=max_size_bytes),
            account=account,
        )
        # materialize() on InlineDestination always returns InlinePayload.
        assert isinstance(result, InlinePayload)
        return inline_payload_to_blocks(result)
    except InlineTooLargeError as e:
        return {
            "success": False,
            "error": str(e),
            "size_bytes": e.size_bytes,
            "cap_bytes": e.cap_bytes,
            "hint": (
                "File is too large to return inline. Read it in pieces "
                "via Drive's UI / API, or share the Drive URL with the "
                "user directly."
            ),
        }
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return {"error": str(e)}


async def drive_move(
    file_id: str,
    destination_folder_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Move a Drive file to a different folder.

    Drive's REST API does not have a literal "move" — a move is an
    update that adds the new parent and removes the old. This tool
    performs both in one API call.

    Args:
        file_id: Drive file ID to move.
        destination_folder_id: Folder ID to move into. Use ``"root"``
            for My Drive root.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``id``, ``name``, ``parents`` (new parent IDs), and
        ``url`` (webViewLink). Returns an error envelope if the file
        or destination folder cannot be reached.
    """
    try:
        return drive.move_file(file_id, destination_folder_id, account=account)
    except Exception as e:
        logger.error(f"Error moving file: {e}")
        return {"error": str(e)}


async def drive_delete(
    file_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Move a Drive file to Trash.

    Uses Trash semantics, not hard-delete: the file becomes invisible
    in Drive listings but the user can restore it from Drive's Trash
    UI for ~30 days. Matches Drive UI expectations and avoids
    irrecoverable destruction from agent error. A separate primitive
    would be needed for permanent (hard) delete.

    Args:
        file_id: Drive file ID to trash.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``file_id`` and ``trashed: true``. Idempotent.
    """
    try:
        return drive.delete_file(file_id=file_id, account=account)
    except Exception as e:
        logger.error(f"Error trashing file: {e}")
        return {"error": str(e)}


async def drive_search(
    query: str,
    max_results: int = 25,
    corpora: str = "user",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Search Drive via the native ``files.list`` query language.

    Drive treats files, folders, and shortcuts as one resource type
    discriminated by ``mime_type``. This tool is the canonical search
    primitive — the same call backs ``drive_list_folder`` and
    ``drive_search_folders`` under the hood. Use it when you need a
    query the convenience tools don't cover.

    The ``query`` string follows Google's
    `Drive search syntax`_. Common recipes:

    - **List files inside a known folder** (matches
      ``drive_list_folder``)::

        "'<folder_id>' in parents and trashed = false"

    - **Find a folder by name** (matches ``drive_search_folders``)::

        "mimeType = 'application/vnd.google-apps.folder' "
        "and name contains 'Projects'"

    - **Find non-folder files by name**::

        "mimeType != 'application/vnd.google-apps.folder' "
        "and name contains 'invoice' and trashed = false"

    - **Find PDFs modified after a date**::

        "mimeType = 'application/pdf' "
        "and modifiedTime > '2026-01-01T00:00:00'"

    - **Full-text search inside Google Docs and indexable files**::

        "fullText contains 'water bill'"

    Args:
        query: Drive query string (see recipes above).
        max_results: Page size (default 25).
        corpora: Which corpora to search. ``"user"`` (default) is My
            Drive plus files shared with the caller. ``"allDrives"``
            adds Shared Drives. ``"domain"`` is files shared to the
            caller's domain.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``items`` (list of file records) and
        ``next_page_token``. Each item carries ``id``, ``name``,
        ``mime_type``, ``modified_time``, ``size`` (``None`` or a
        placeholder for native Google Workspace formats — do not treat
        as a real byte count for Google-native files), ``parents``, and
        ``url``.
        Shortcuts also include ``target_id`` and ``target_mime_type``.

    .. _Drive search syntax:
       https://developers.google.com/drive/api/guides/search-files
    """
    try:
        return drive.search_drive(
            query=query,
            max_results=max_results,
            corpora=corpora,
            account=account,
        )
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error searching Drive: {e}")
        return {"error": str(e)}


async def drive_get_metadata(
    file_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Fetch metadata for a single Drive file or folder by ID.

    Useful for pre-flight checks before ``drive_download`` — inspect
    ``size`` and ``mime_type`` to decide whether to fetch inline (the
    100,000-byte default cap applies) or to leave the file in Drive
    and operate on it via ``drive_move`` / ``drive_delete`` / sharing.

    Args:
        file_id: Drive file ID.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``id``, ``name``, ``mime_type``, ``size`` (``None``
        or a placeholder for native Google Workspace formats — do not
        treat as a real byte count for Google-native files), ``parents`` (folder
        IDs), ``modified_time``, ``url`` (webViewLink), ``trashed``,
        and — for shortcuts — ``target_id`` and ``target_mime_type``.
    """
    try:
        return drive.get_metadata(file_id=file_id, account=account)
    except Exception as e:
        logger.error(f"Error fetching Drive metadata: {e}")
        return {"error": str(e)}


async def drive_find_folder(
    path: str,
    drive_id: str = "my_drive",
    folder_id: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Find a folder by navigating a path from a starting location.

    Args:
        path: Folder path with '/' separators (e.g.,
            "Projects/my-project").
        drive_id: Starting drive — "my_drive" (default) or a Shared
            Drive ID. Ignored if ``folder_id`` is provided.
        folder_id: Start from this folder ID instead of a drive root.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with folder ``id``, ``name``, and ``path``. Returns an
        error envelope if not found or ambiguous.
    """
    try:
        result = drive.find_folder_by_path(
            path, drive=drive_id, folder_id=folder_id, account=account
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
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Search for folders by name across all accessible locations.

    One API call. Searches My Drive, Shared Drives, and shared-with-me
    folders.

    Args:
        name: Folder name to search for.
        match: "contains" (default) or "exact" match. Case-insensitive.
        limit: Maximum results to return (default 50).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``folders`` list (each with ``id``, ``name``,
        ``parents``, ``created_time``, ``modified_time``, ``drive_id``)
        and ``count``.
    """
    try:
        if match not in ("contains", "exact"):
            return {"error": f"Invalid match type: {match}. Use 'contains' or 'exact'."}
        results = drive.search_folders(name, match=match, limit=limit, account=account)
        return {"folders": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Error searching folders: {e}")
        return {"error": str(e)}
