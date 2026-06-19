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
import mimetypes
import os
import shlex
from typing import Any, Optional

from googleapiclient.errors import HttpError

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
    decode_inline_upload,
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


def _upload_session_response(
    session_uri: str, name: str, local_path: Optional[str] = None
) -> dict[str, Any]:
    """Shape the out-of-band (direct-to-Google) upload response."""
    target = shlex.quote(local_path) if local_path else "<your-file>"
    return {
        "mode": "out_of_band",
        "upload_url": session_uri,
        "name": name,
        "run": f"curl -fL -T {target} {shlex.quote(session_uri)}",
        "note": (
            "PUT the file bytes to upload_url with NO auth header (the URL "
            "is self-authorizing) — the bytes go straight to Google, any "
            "size. On a shell-less client this large-upload path isn't "
            "available; use a small inline upload (content_base64) instead."
        ),
    }


async def drive_upload(
    name: Optional[str] = None,
    local_path: Optional[str] = None,
    content_base64: Optional[str] = None,
    folder_id: Optional[str] = None,
    keep_revision_forever: bool = False,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Upload a new file to Google Drive. Provide the content one of two ways.

    You pick based on what you have — never on how the bytes travel:

    - **You have a local file** → pass ``local_path``. On a local (stdio)
      server it's read and uploaded directly — **any size, no base64**.
      On a remote (HTTP) server the tool returns a self-authorizing
      upload URL and a ready-to-run ``curl -T`` command for your
      ``local_path``; the bytes go **straight to Google**, no size limit.
    - **You have the bytes in hand** (small) → pass ``content_base64``.
      Works on any transport; subject to the inline size cap.

    On a remote server you may omit both to get a bare upload URL to PUT
    your bytes to. ``name`` defaults to the ``local_path`` basename.

    Args:
        name: File name in Drive. Defaults to the ``local_path`` basename;
            required for an inline or URL upload that has no path.
        local_path: Path to a local file (see above).
        content_base64: Base64-encoded content for a small inline upload.
        folder_id: Destination folder ID. ``None``/``"root"`` = My Drive.
        keep_revision_forever: Pin the initial revision (``keepForever``).
            Applies to the direct stdio/inline uploads; the out-of-band
            URL path does not set it.
        account: Optional account selector (name or email).

    Returns:
        Completed upload → dict with file ``id``, ``name``, ``url``,
        ``keep_revision_forever``. Out-of-band path → dict with
        ``mode="out_of_band"``, ``upload_url`` and a ``run`` command.
    """
    try:
        if content_base64 is not None:
            data, src_name, mime_type = decode_inline_upload(content_base64, name=name)
            final_name = name or src_name
            if not final_name:
                return {"error": "Provide 'name' for an inline upload."}
            return drive.upload_bytes(
                data=data, name=final_name, mime_type=mime_type,
                folder_id=folder_id,
                keep_revision_forever=keep_revision_forever, account=account,
            )

        if local_path is not None:
            final_name = name or os.path.basename(local_path)
            # If the server can see the file, it shares the agent's
            # filesystem (stdio) → read + upload directly, any size.
            if os.path.isfile(local_path):
                return drive.upload_file(
                    local_path=local_path, folder_id=folder_id, name=name,
                    keep_revision_forever=keep_revision_forever, account=account,
                )
            # The server can't see the file → remote (HTTP). Hand back a
            # direct-to-Google resumable session URL to PUT the bytes to.
            mime_type, _ = mimetypes.guess_type(final_name)
            session_uri = drive.begin_resumable_upload(
                name=final_name,
                mime_type=mime_type or "application/octet-stream",
                folder_id=folder_id, account=account,
            )
            return _upload_session_response(session_uri, final_name, local_path)

        # Neither inline nor a path → start an upload session to PUT to.
        if not name:
            return {
                "error": "Provide content_base64 (small), local_path, or a "
                         "name to start an upload session."
            }
        session_uri = drive.begin_resumable_upload(
            name=name, folder_id=folder_id, account=account,
        )
        return _upload_session_response(session_uri, name)
    except InlineSourceTooLargeError as e:
        return {
            "success": False, "error": str(e),
            "size_bytes": e.size_bytes, "cap_bytes": e.cap_bytes,
            "hint": (
                "Too large to inline. Pass local_path instead — on a remote "
                "server you'll get a direct-to-Google upload URL."
            ),
        }
    except InvalidInlineSourceError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return {"error": str(e)}


async def drive_update(
    file_id: str,
    local_path: Optional[str] = None,
    content_base64: Optional[str] = None,
    name: Optional[str] = None,
    keep_revision_forever: bool = False,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Replace an existing Drive file's content. Same input modes as drive_upload.

    - **``local_path``** → stdio: read + update directly (any size);
      HTTP: returns a self-authorizing resumable *update* URL + ``curl
      -T`` command (bytes go straight to Google).
    - **``content_base64``** → small inline update, any transport.

    Revisions stack on ``file_id`` either way.

    Args:
        file_id: Drive file ID to update.
        local_path: Path to a local file with the new content.
        content_base64: Base64 content for a small inline update.
        name: Optional new name for the file.
        keep_revision_forever: Pin the resulting head revision
            (``keepForever``) — applies to the direct stdio/inline path;
            the out-of-band URL path does not set it.
        account: Optional account selector (name or email).

    Returns:
        Completed update → dict with file ``id``, ``name``, ``url``.
        Out-of-band path → dict with ``mode="out_of_band"`` + ``run``.
    """
    try:
        if content_base64 is not None:
            data, _n, mime_type = decode_inline_upload(content_base64, name=name)
            return drive.update_bytes(
                file_id=file_id, data=data, mime_type=mime_type, new_name=name,
                keep_revision_forever=keep_revision_forever, account=account,
            )

        if local_path is not None:
            # Server can see the file → stdio → update directly, any size.
            if os.path.isfile(local_path):
                return drive.update_file(
                    file_id=file_id, local_path=local_path, new_name=name,
                    keep_revision_forever=keep_revision_forever, account=account,
                )
            # Can't see it → remote → resumable update session URL.
            mime_type, _ = mimetypes.guess_type(local_path)
            session_uri = drive.begin_resumable_update(
                file_id=file_id,
                mime_type=mime_type or "application/octet-stream",
                new_name=name, account=account,
            )
            return _upload_session_response(session_uri, name or file_id, local_path)

        session_uri = drive.begin_resumable_update(
            file_id=file_id, new_name=name, account=account,
        )
        return _upload_session_response(session_uri, name or file_id)
    except InlineSourceTooLargeError as e:
        return {
            "success": False, "error": str(e),
            "size_bytes": e.size_bytes, "cap_bytes": e.cap_bytes,
            "hint": "Too large to inline. Pass local_path for a resumable update URL.",
        }
    except InvalidInlineSourceError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error updating file: {e}")
        return {"error": str(e)}


async def drive_download(
    file_id: str,
    save_to: Optional[str] = None,
    account: Optional[str] = None,
) -> list[ContentBlock] | dict[str, Any]:
    """Download a Drive file's contents. Transport is chosen automatically.

    The caller never picks how the bytes travel:

    - **``save_to`` (local/stdio server only)** → stream the file
      straight to that local path, **any size, no base64**. This is the
      one-step path when the server shares your filesystem (stdio). It is
      rejected on a remote (HTTP) server, which can't write to your disk
      — omit it there and use the returned URL.
    - **Small files** (≤ ~60 KB), no ``save_to`` → returned **inline** as
      ``[TextContent summary, EmbeddedResource]`` (base64), so the agent
      gets the bytes directly under any transport, including
      browser/mobile MCP connectors.
    - **Larger files**, no ``save_to`` → a **Drive download link**. The
      file is already in the user's Drive, so opening the link in a
      browser signed in to that account downloads it — no server proxy,
      no token, no size cap. (Prefer ``save_to`` on a local server to get
      the file straight to disk.)

    Args:
        file_id: Drive file ID to fetch.
        save_to: Local path to write to — local/stdio server only.
        account: Optional account selector (name or email). Omit to use
            the user's default account.
    """
    try:
        # save_to is meaningful only when the server shares the agent's
        # filesystem (stdio). If the target directory exists on the
        # server, write straight to it — any size, no base64.
        if save_to is not None:
            parent = os.path.dirname(os.path.abspath(save_to))
            if os.path.isdir(parent):
                result = drive.download_file(file_id, save_to, account=account)
                return {
                    "mode": "saved",
                    "path": result["file_path"],
                    "size_bytes": result.get("size"),
                    "name": result.get("name"),
                }
            # Directory not present on the server → remote (HTTP); can't
            # write the agent's disk. Fall through to the Drive link.

        meta = drive.get_download_metadata(file_id, account=account)
        raw_size = meta.get("size")
        size = int(raw_size) if raw_size not in (None, "") else None
        name = meta.get("name") or f"drive-{file_id[:8]}"
        mime_type = meta.get("mime_type") or "application/octet-stream"

        # Small + known size → inline (works on every client).
        if size is not None and size <= DEFAULT_INLINE_SIZE_CAP_BYTES:
            try:
                fetched = drive.download_bytes(file_id=file_id, account=account)
                result = materialize(
                    fetched["data"],
                    name=fetched["name"] or name,
                    mime_type=fetched["mime_type"] or mime_type,
                    destination=InlineDestination(),
                    account=account,
                )
                assert isinstance(result, InlinePayload)
                return inline_payload_to_blocks(result)
            except InlineTooLargeError:
                # Size metadata was stale/under-reported — fall through to
                # the Drive link, which has no size cap.
                pass

        # Large (or unknown size) → a Drive download link. The file is
        # already in the user's Drive and their browser is signed in, so
        # opening this link downloads it — no server proxy, no token.
        link = meta.get("web_content_link") or meta.get("web_view_link")
        return {
            "mode": "link",
            "url": link,
            "name": name,
            "size_bytes": size,
            "mime_type": mime_type,
            "note": (
                "Too large to return inline. Open this link in a browser "
                "signed in to this Google account to download the file. On a "
                "local (stdio) server, pass save_to=<path> to write it "
                "straight to disk instead."
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


async def drive_set_properties(
    file_id: str,
    properties: Optional[dict] = None,
    app_properties: Optional[dict] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Set custom key/value metadata on a Drive file or folder.

    Use this to tag a file for later programmatic discovery — e.g. mark
    a backing spreadsheet so a skill can find it by tag instead of a
    hardcoded ID. Tag once; discover thereafter with ``drive_search``
    using ``properties has { key='...' and value='...' }``.

    Two maps are available:

    - ``properties`` — visible to any app with file access. One shared
      namespace across apps, so **namespace your keys** (e.g.
      ``myapp``). Use this for cross-environment discovery
      (cloud connector + local CLI + mobile all see it).
    - ``app_properties`` — private to the OAuth client that wrote them;
      other clients can't see them. Good for secrecy, **bad for
      cross-client discovery**.

    The update is a **per-key merge** in a single API call: a key in
    the map is added/updated; a key with value ``null`` is deleted;
    keys not mentioned are left untouched (never clobbers other apps'
    tags). No read-before-write. These tags are API-only — they never
    appear in the Drive/Docs/Sheets UI and do not travel with a
    downloaded copy.

    Args:
        file_id: Drive file or folder ID.
        properties: Public custom properties to merge (``null`` value
            deletes a key).
        app_properties: App-private custom properties to merge.
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict with ``id``, ``name``, and the resulting ``properties`` /
        ``app_properties`` maps. Error envelope if neither map is given
        or the file can't be reached.
    """
    try:
        return drive.set_properties(
            file_id,
            properties=properties,
            app_properties=app_properties,
            account=account,
        )
    except ValueError as e:
        return {"error": str(e)}
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error setting properties: {e}")
            return {
                "error": "The caller does not have permission.",
                "details": str(e),
                "hint": (
                    "The chosen gwsa account may not have edit access to "
                    "this file. Try a different account via the 'account' "
                    "parameter (see 'list_google_accounts')."
                ),
            }
        raise
    except Exception as e:
        logger.error(f"Error setting properties: {e}")
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


async def drive_list_revisions(
    file_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List a Drive file's revision history.

    Every ``drive_update`` mints a new revision. For an uploaded
    (non-native) file the revisions act as a lightweight version store:
    enumerate history here, fetch a past version's content with
    ``drive_get_revision`` to diff, and pin milestones with
    ``drive_keep_revision`` so they survive auto-pruning (Drive prunes
    non-pinned revisions roughly after 100 versions or 30 days). Native
    Google files (Docs/Sheets/Slides) can be listed but their historical
    content is not exportable.

    Args:
        file_id: Drive file ID.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``file_id`` and ``items`` — each revision carries
        ``id``, ``modified_time``, ``keep_forever``, ``size``,
        ``md5_checksum``, ``mime_type``, ``original_filename``, and
        ``last_modifying_user``. On error returns ``{"error": str}``.
    """
    try:
        return drive.list_revisions(file_id=file_id, account=account)
    except Exception as e:
        logger.error(f"Error listing revisions: {e}")
        return {"error": str(e)}


async def drive_get_revision(
    file_id: str,
    revision_id: str,
    max_size_bytes: Optional[int] = None,
    account: Optional[str] = None,
) -> list[ContentBlock] | dict[str, Any]:
    """Fetch a specific revision's content inline as an MCP EmbeddedResource.

    Returns ``[TextContent summary, EmbeddedResource]`` with the bytes
    base64-encoded, so the agent receives a past version directly under
    any transport — ready to diff against the current file.

    Content is retrievable only for **uploaded (non-native) files**.
    For a native Google file (Docs/Sheets/Slides) this returns an error
    envelope with ``native_file: true`` — the API exposes such revisions'
    metadata (via ``drive_list_revisions``) but not their historical
    content.

    Args:
        file_id: Drive file ID.
        revision_id: Revision ID (from ``drive_list_revisions``).
        max_size_bytes: Override the default inline size cap on raw bytes
            (default 60,000 — sized so base64 + envelope fits inside
            Claude Code's tool-response budget). Larger revisions return
            an error envelope; use ``drive_get_revision`` with ``--out``
            via the CLI, or fetch in another way.
        account: Optional account selector (name or email). Omit to
            use the user's default account.
    """
    try:
        fetched = drive.download_revision_bytes(
            file_id=file_id, revision_id=revision_id, account=account
        )
        result = materialize(
            fetched["data"],
            name=fetched["name"],
            mime_type=fetched["mime_type"],
            destination=InlineDestination(max_size_bytes=max_size_bytes),
            account=account,
        )
        assert isinstance(result, InlinePayload)
        return inline_payload_to_blocks(result)
    except drive.NativeFileRevisionError as e:
        return {
            "success": False,
            "error": str(e),
            "native_file": True,
            "mime_type": e.mime_type,
        }
    except InlineTooLargeError as e:
        return {
            "success": False,
            "error": str(e),
            "size_bytes": e.size_bytes,
            "cap_bytes": e.cap_bytes,
            "hint": (
                "Revision is too large to return inline. Fetch it via the "
                "CLI (`gwsa drive revisions get <file> <rev> --out PATH`)."
            ),
        }
    except Exception as e:
        logger.error(f"Error fetching revision: {e}")
        return {"error": str(e)}


async def drive_keep_revision(
    file_id: str,
    revision_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Pin a revision (``keepForever=true``) so it is never auto-pruned.

    Use this to protect a milestone version of an uploaded file from
    Drive's 100-version / 30-day prune. Drive caps pinned revisions at
    ~200 per file.

    Args:
        file_id: Drive file ID.
        revision_id: Revision ID to pin (from ``drive_list_revisions``).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        The updated revision (normalized shape) with ``keep_forever``
        true. On error returns ``{"error": str}``.
    """
    try:
        return drive.keep_revision(
            file_id=file_id, revision_id=revision_id, account=account
        )
    except Exception as e:
        logger.error(f"Error pinning revision: {e}")
        return {"error": str(e)}


async def drive_unkeep_revision(
    file_id: str,
    revision_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Remove the keep-forever pin from a revision (``keepForever=false``).

    Drive only allows unpinning the **head (current)** revision. Once a
    non-head (older) revision is pinned, the API refuses to unpin it —
    this returns an envelope with ``keep_forever_locked: true`` rather
    than raising. Pin older milestones deliberately.

    Args:
        file_id: Drive file ID.
        revision_id: Revision ID to unpin (from ``drive_list_revisions``).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        The updated revision (normalized shape) with ``keep_forever``
        false. On error returns ``{"error": str}``.
    """
    try:
        return drive.unkeep_revision(
            file_id=file_id, revision_id=revision_id, account=account
        )
    except drive.KeepForeverUnsetError as e:
        return {
            "success": False,
            "error": str(e),
            "keep_forever_locked": True,
        }
    except Exception as e:
        logger.error(f"Error unpinning revision: {e}")
        return {"error": str(e)}
