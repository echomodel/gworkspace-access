"""Google Drive file revision operations.

Drive's ``revisions`` resource turns an uploaded (non-native) file into
a lightweight, server-side version store: every ``files.update`` mints a
new revision whose content is retrievable, and milestones can be pinned
so they survive auto-pruning.

Behavior that callers must understand (and that the CLI/MCP layers
surface explicitly):

- **Content is retrievable only for non-native files.** For uploaded
  files (JSON, CSV, DOCX, PDF, images, …) a specific revision's bytes
  come back via ``revisions.get`` with ``alt=media``. For **native
  Google files** (Docs/Sheets/Slides, mimeType
  ``application/vnd.google-apps.*``) revisions can be *listed* but their
  historical content is **not** exportable through the API —
  :func:`download_revision_bytes` raises :class:`NativeFileRevisionError`
  rather than failing opaquely.
- **Auto-pruning.** Non-pinned revisions of uploaded files are pruned
  (roughly after 100 versions or 30 days). Pin a revision with
  ``keepForever=true`` (:func:`keep_revision`) to keep it indefinitely.
  There is a cap of ~200 ``keepForever`` revisions per file.
- **No writable revision name.** The API exposes no writable
  name/description on a revision — only ``keepForever``, ``published``,
  timestamps, checksums, and size. Human "commit messages" must live in
  the file content itself, not on the revision.
"""

import hashlib
import io
import os
from typing import Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from .service import get_drive_service

_NATIVE_MIME_PREFIX = "application/vnd.google-apps."

_REVISION_LIST_FIELDS = (
    "revisions(id, modifiedTime, keepForever, size, md5Checksum, "
    "mimeType, originalFilename, "
    "lastModifyingUser(displayName, emailAddress)), nextPageToken"
)

_REVISION_GET_FIELDS = (
    "id, modifiedTime, keepForever, size, md5Checksum, mimeType, "
    "originalFilename, lastModifyingUser(displayName, emailAddress)"
)


class NativeFileRevisionError(Exception):
    """Raised when historical *content* of a native Google file revision
    is requested.

    The Drive API can list revisions of a native Google file (Docs,
    Sheets, Slides) but cannot export their historical content via
    ``alt=media``. Revision-content download is supported only for
    uploaded (non-native) files. Callers should catch this and surface
    the limitation rather than treating it as a generic failure.
    """

    def __init__(self, file_id: str, revision_id: str, mime_type: str):
        self.file_id = file_id
        self.revision_id = revision_id
        self.mime_type = mime_type
        super().__init__(
            "Revision content is not exportable for native Google files "
            f"(mimeType '{mime_type}'). The Drive API exposes revision "
            "metadata for native files but not their historical content; "
            "revision-content download is supported only for uploaded "
            "(non-native) files."
        )


class KeepForeverUnsetError(Exception):
    """Raised when unpinning a revision (``keepForever=false``) is
    rejected by Drive.

    Discovered against the live API: Drive only allows toggling
    ``keepForever`` **both ways on the head (current) revision**. Once a
    **non-head (older)** revision is pinned, the API refuses to unpin it
    (reason ``illegalKeepForeverModification``) — the pin is effectively
    permanent for that older revision. Pin older milestones
    deliberately; you cannot un-pin them through the API afterward.
    """

    def __init__(self, file_id: str, revision_id: str):
        self.file_id = file_id
        self.revision_id = revision_id
        super().__init__(
            "Drive rejected unpinning this revision "
            "(keepForever cannot be set to false). Drive only allows "
            "toggling keepForever both ways on the head (current) "
            "revision; once a non-head (older) revision is pinned, it "
            "cannot be un-pinned through the API. Pin older milestones "
            "deliberately."
        )


def _is_native(mime_type: Optional[str]) -> bool:
    return bool(mime_type) and mime_type.startswith(_NATIVE_MIME_PREFIX)


def _normalize_revision(rev: dict) -> dict:
    """Reshape a raw Drive revision into the gwsa snake_case shape."""
    user = rev.get("lastModifyingUser") or {}
    return {
        "id": rev.get("id"),
        "modified_time": rev.get("modifiedTime"),
        "keep_forever": rev.get("keepForever", False),
        "size": rev.get("size"),
        "md5_checksum": rev.get("md5Checksum"),
        "mime_type": rev.get("mimeType"),
        "original_filename": rev.get("originalFilename"),
        "last_modifying_user": (
            user.get("displayName") or user.get("emailAddress")
        ),
    }


def list_revisions(file_id: str, account: Optional[str] = None) -> dict:
    """List a Drive file's revision history (newest enumeration order
    follows the API — typically oldest first).

    Works for both uploaded and native files; for native files only
    metadata is available (historical content is not exportable — see
    :func:`download_revision_bytes`). Fully paginates, since the revision
    count per file is bounded by Drive's pruning + keep-forever caps.

    Args:
        file_id: The Drive file ID.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with ``file_id`` and ``items`` — each item carries ``id``,
        ``modified_time``, ``keep_forever``, ``size``, ``md5_checksum``,
        ``mime_type``, ``original_filename``, and ``last_modifying_user``.
    """
    service = get_drive_service(account=account)
    items: list[dict] = []
    page_token: Optional[str] = None
    while True:
        resp = service.revisions().list(
            fileId=file_id,
            pageSize=200,
            fields=_REVISION_LIST_FIELDS,
            pageToken=page_token,
        ).execute()
        for rev in resp.get("revisions", []):
            items.append(_normalize_revision(rev))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return {"file_id": file_id, "items": items}


def _fetch_revision_bytes(
    service, file_id: str, revision_id: str
) -> tuple[bytes, dict]:
    """Fetch one revision's bytes plus its metadata.

    Raises :class:`NativeFileRevisionError` for native Google files,
    whose historical content the API cannot export.
    """
    meta = service.revisions().get(
        fileId=file_id,
        revisionId=revision_id,
        fields=_REVISION_GET_FIELDS,
    ).execute()

    if _is_native(meta.get("mimeType")):
        raise NativeFileRevisionError(
            file_id, revision_id, meta.get("mimeType", "")
        )

    request = service.revisions().get_media(
        fileId=file_id, revisionId=revision_id
    )
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue(), meta


def download_revision_bytes(
    file_id: str, revision_id: str, account: Optional[str] = None
) -> dict:
    """Download a specific revision's content into memory.

    The in-memory variant used by MCP tools (which must work under HTTP
    transport). For native Google files, raises
    :class:`NativeFileRevisionError`.

    Args:
        file_id: The Drive file ID.
        revision_id: The revision ID (from :func:`list_revisions`).
        account: Optional account selector — name or email.

    Returns:
        Dict with ``data`` (bytes), ``name``, ``mime_type``,
        ``size_bytes``, and ``revision_id``.
    """
    service = get_drive_service(account=account)
    data, meta = _fetch_revision_bytes(service, file_id, revision_id)
    return {
        "data": data,
        "name": meta.get("originalFilename") or f"{file_id}-{revision_id}",
        "mime_type": meta.get("mimeType") or "application/octet-stream",
        "size_bytes": len(data),
        "revision_id": revision_id,
    }


def download_revision_file(
    file_id: str,
    revision_id: str,
    save_path: str,
    account: Optional[str] = None,
) -> dict:
    """Download a specific revision's content to a local filesystem path.

    The disk variant used by the CLI. For native Google files, raises
    :class:`NativeFileRevisionError`.

    Args:
        file_id: The Drive file ID.
        revision_id: The revision ID (from :func:`list_revisions`).
        save_path: Local path where the revision content should be saved.
        account: Optional account selector — name or email.

    Returns:
        Dict with ``success``, ``file_path``, ``size``, ``name``,
        ``mime_type``, and ``revision_id``.
    """
    service = get_drive_service(account=account)
    data, meta = _fetch_revision_bytes(service, file_id, revision_id)

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(data)

    return {
        "success": True,
        "file_path": save_path,
        "size": len(data),
        "name": meta.get("originalFilename"),
        "mime_type": meta.get("mimeType"),
        "revision_id": revision_id,
    }


def match_revision_bytes(
    file_id: str,
    data: bytes,
    pin: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Find the revision whose content matches the given bytes, by md5.

    Computes the md5 of ``data`` and scans the file's revisions for one
    whose ``md5Checksum`` equals it — answering "is this exact content
    already backed up as a revision, and which one?" without downloading
    anything. If multiple revisions share the content, the **oldest**
    match is returned (the earliest time that content existed).

    Args:
        file_id: The Drive file ID.
        data: Local content to look for.
        pin: If a match is found, pin it (``keepForever``) so it survives
            auto-pruning — match-and-pin in one call.
        account: Optional account selector — name or email.

    Returns:
        Dict with ``file_id``, ``md5`` (the local content's checksum),
        ``matched`` (bool), ``revision`` (the matched revision's ``id``,
        ``keep_forever``, ``modified_time``, ``size`` — or ``None``), and
        ``pinned`` (bool). For native Google files (no checksums) adds a
        ``note`` and returns ``matched: false``.
    """
    local_md5 = hashlib.md5(data).hexdigest()
    items = list_revisions(file_id, account=account)["items"]

    result: dict = {
        "file_id": file_id,
        "md5": local_md5,
        "matched": False,
        "revision": None,
        "pinned": False,
    }

    if items and not any(r.get("md5_checksum") for r in items):
        result["note"] = (
            "Revisions carry no md5 checksum (native Google file); "
            "content-hash match does not apply to native files."
        )
        return result

    match = next(
        (r for r in items if r.get("md5_checksum") == local_md5), None
    )
    if not match:
        return result

    result["matched"] = True
    result["revision"] = {
        "id": match.get("id"),
        "keep_forever": match.get("keep_forever"),
        "modified_time": match.get("modified_time"),
        "size": match.get("size"),
    }

    if pin:
        if match.get("keep_forever"):
            result["pinned"] = True  # already pinned, idempotent
        else:
            pinned = keep_revision(file_id, match["id"], account=account)
            result["revision"]["keep_forever"] = pinned.get("keep_forever")
            result["pinned"] = True

    return result


def match_revision_file(
    file_id: str,
    local_path: str,
    pin: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Find the revision matching a local file's content (by md5).

    Disk-reading wrapper over :func:`match_revision_bytes` for the CLI.
    See that function for the return shape.
    """
    with open(local_path, "rb") as f:
        data = f.read()
    return match_revision_bytes(file_id, data, pin=pin, account=account)


def _set_keep_forever(
    file_id: str,
    revision_id: str,
    keep_forever: bool,
    account: Optional[str] = None,
) -> dict:
    service = get_drive_service(account=account)
    try:
        updated = service.revisions().update(
            fileId=file_id,
            revisionId=revision_id,
            body={"keepForever": keep_forever},
            fields=_REVISION_GET_FIELDS,
        ).execute()
    except HttpError as e:
        # Drive refuses to unpin a non-head revision once it is pinned.
        if not keep_forever and "illegalKeepForeverModification" in str(e):
            raise KeepForeverUnsetError(file_id, revision_id) from e
        raise
    return _normalize_revision(updated)


def keep_revision(
    file_id: str, revision_id: str, account: Optional[str] = None
) -> dict:
    """Pin a revision (``keepForever=true``) so it is never auto-pruned.

    Drive caps pinned revisions at ~200 per file. Pinning is how a
    caller protects a milestone version of an uploaded file from the
    100-version / 30-day prune.

    Args:
        file_id: The Drive file ID.
        revision_id: The revision ID to pin.
        account: Optional account selector — name or email.

    Returns:
        The updated revision in the normalized shape (``keep_forever``
        will be ``True``).
    """
    return _set_keep_forever(file_id, revision_id, True, account=account)


def unkeep_revision(
    file_id: str, revision_id: str, account: Optional[str] = None
) -> dict:
    """Remove the keep-forever pin from a revision (``keepForever=false``).

    **Drive asymmetry (verified against the live API):** unpinning only
    works on the **head (current)** revision. Once a **non-head (older)**
    revision is pinned, Drive refuses to unpin it and this raises
    :class:`KeepForeverUnsetError`. Pinning an old milestone is therefore
    effectively permanent — pin deliberately.

    Args:
        file_id: The Drive file ID.
        revision_id: The revision ID to unpin.
        account: Optional account selector — name or email.

    Returns:
        The updated revision in the normalized shape (``keep_forever``
        will be ``False``).

    Raises:
        KeepForeverUnsetError: if the revision is a pinned non-head
            revision, which Drive will not un-pin.
    """
    return _set_keep_forever(file_id, revision_id, False, account=account)
