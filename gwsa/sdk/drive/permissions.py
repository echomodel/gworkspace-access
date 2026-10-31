"""Google Drive sharing: the ``permissions`` resource.

A file's sharing is its list of permissions, each one a grant of a
``role`` (``owner``, ``writer``, ``commenter``, ``reader``) to a
``type`` of principal (``user``, ``group``, ``domain``, ``anyone``).
Two operations cover every sharing change:

- :func:`list_permissions` — ``permissions.list``, returned as the API
  gives them. ``permissionDetails.inherited`` says whether a grant comes
  from a parent folder; such a grant is changed on that folder, not on
  the file.
- :func:`set_permission` — one ``role`` argument chooses the API call:
  create or update a grant (lowering a role as well as raising it),
  delete it (``none``), start an ownership transfer (``pending_owner``),
  or accept one (``owner``). Each call is one grant on one file; folders
  pass their grants down, and walking a tree belongs to the caller.

Ownership transfer between consumer accounts is the two-step flow in
https://developers.google.com/workspace/drive/api/guides/transfer-file:
the owner sets ``pendingOwner`` on the recipient's ``writer`` grant
(Drive sends the invitation), then the recipient updates their own grant
with ``role=owner`` and ``transferOwnership=true``.
"""

from __future__ import annotations

import json
from typing import Optional

from googleapiclient.errors import HttpError

from ..auth import get_google_account_creds
from .service import get_drive_service

_PERMISSION_FIELDS = (
    "id, type, emailAddress, domain, role, displayName, pendingOwner, "
    "permissionDetails(inherited, inheritedFrom, role, permissionType)"
)

ROLES = ("reader", "commenter", "writer", "none", "pending_owner", "owner")
TYPES = ("user", "group", "anyone")


class PermissionError_(ValueError):
    """A sharing change refused before or by the API, with the facts."""


class PermissionNotFoundError(PermissionError_):
    """No grant on the file matches the principal to change or remove."""


class OwnerRemovalRefusedError(PermissionError_):
    """``none`` was asked for the owner's grant, which Drive cannot remove."""


class InheritedPermissionError(PermissionError_):
    """The grant comes from a parent folder and can only be changed there."""

    def __init__(self, file_id: str, inherited_from: Optional[str]):
        self.file_id = file_id
        self.inherited_from = inherited_from
        where = (
            f"the folder {inherited_from}" if inherited_from
            else "a parent folder"
        )
        super().__init__(
            f"This grant is inherited from {where}; Drive does not change an "
            "inherited grant on the file. Change it on that folder, or move "
            "the file out of it."
        )


def list_permissions(file_id: str, account: Optional[str] = None) -> dict:
    """List every grant on a file — ``permissions.list``, as the API returns it.

    Each permission carries ``id``, ``type``, ``role``, ``emailAddress``
    (user/group) or ``domain``, ``displayName``, ``pendingOwner`` (a
    transfer awaiting acceptance), and ``permissionDetails`` with
    ``inherited`` / ``inheritedFrom`` when the grant comes from a parent
    folder.

    Returns:
        Dict with ``file_id`` and ``permissions`` (list, all pages).
    """
    service = get_drive_service(account=account)
    return {
        "file_id": file_id,
        "permissions": _fetch_permissions(service, file_id),
    }


def set_permission(
    file_id: str,
    role: str,
    email: Optional[str] = None,
    type: str = "user",
    account: Optional[str] = None,
) -> dict:
    """Change one grant on a file; ``role`` picks the API call.

    ======================= ===================================================
    ``role``                API call
    ======================= ===================================================
    ``reader`` / ``commenter`` / ``writer``
                            ``permissions.update`` of the principal's existing
                            grant (lowering as well as raising), or
                            ``permissions.create`` when it has none.
    ``none``                ``permissions.delete`` of the principal's grant.
    ``pending_owner``       ``role=writer, pendingOwner=true`` on the user's
                            grant (update or create). Starts a consumer-account
                            transfer; Drive emails the invitation.
    ``owner``               ``role=owner, transferOwnership=true`` on a grant.
                            With no ``email``, the caller's own grant: this
                            accepts a transfer offered to the account.
    ======================= ===================================================

    ``type="anyone"`` with ``reader`` / ``commenter`` / ``writer`` turns
    link sharing on; with ``none`` it turns link sharing off. ``email`` is
    required for ``user`` and ``group`` (except ``owner`` accepting), and
    not allowed for ``anyone``.

    No notification email is sent, except for ``pending_owner`` on a new
    grant, where Drive requires it.

    Returns:
        Dict with ``file_id``, ``action`` (``created`` / ``updated`` /
        ``deleted``), ``permission`` (the resulting grant, ``None`` after a
        delete) and ``permissions`` (the file's full list afterwards).

    Raises:
        ValueError: unknown ``role`` or ``type``, or ``email`` missing /
            misplaced.
        PermissionNotFoundError: ``none`` (or ``owner`` accepting) with no
            matching grant on the file.
        OwnerRemovalRefusedError: ``none`` on the owner's grant.
        InheritedPermissionError: the grant is inherited from a parent
            folder (Drive's ``cannotModifyInheritedPermission``).
        HttpError: any other Drive rejection, unchanged.
    """
    if role not in ROLES:
        raise ValueError(
            f"Unknown role {role!r}. Roles: {', '.join(ROLES)}.")
    if type not in TYPES:
        raise ValueError(
            f"Unknown type {type!r}. Types: {', '.join(TYPES)}.")
    if type == "anyone":
        if email is not None:
            raise ValueError("type='anyone' takes no email.")
        if role in ("pending_owner", "owner"):
            raise ValueError(f"role={role!r} needs a user, not 'anyone'.")
    elif role == "pending_owner" and type != "user":
        raise ValueError("role='pending_owner' needs type='user'.")

    creds, chosen = get_google_account_creds(account=account)
    caller_email = chosen.email
    if email is None and type != "anyone":
        if role == "owner":
            email = caller_email
        else:
            raise ValueError(f"role={role!r} needs an email for type={type!r}.")

    service = get_drive_service(account=account)
    existing = _find_permission(_fetch_permissions(service, file_id),
                                type=type, email=email)
    common = {"fileId": file_id, "supportsAllDrives": True,
              "fields": _PERMISSION_FIELDS}

    try:
        if role == "none":
            if existing is None:
                raise PermissionNotFoundError(_no_grant(type, email))
            if existing.get("role") == "owner":
                raise OwnerRemovalRefusedError(
                    "The owner's grant cannot be removed. Transfer ownership "
                    "instead: role='pending_owner' with the new owner's email, "
                    "then that account accepts with role='owner'."
                )
            service.permissions().delete(
                fileId=file_id, permissionId=existing["id"],
                supportsAllDrives=True,
            ).execute()
            action, permission = "deleted", None

        elif role == "pending_owner":
            if existing is not None:
                permission = service.permissions().update(
                    permissionId=existing["id"],
                    body={"role": "writer", "pendingOwner": True},
                    **common,
                ).execute()
                action = "updated"
            else:
                permission = service.permissions().create(
                    body={"type": "user", "role": "writer",
                          "emailAddress": email, "pendingOwner": True},
                    sendNotificationEmail=True,
                    **common,
                ).execute()
                action = "created"

        elif role == "owner":
            if existing is not None:
                permission = service.permissions().update(
                    permissionId=existing["id"],
                    body={"role": "owner"},
                    transferOwnership=True,
                    **common,
                ).execute()
                action = "updated"
            elif email == caller_email:
                raise PermissionNotFoundError(
                    f"{caller_email} has no grant on this file, so there is "
                    "no pending transfer to accept. The current owner starts "
                    "one with role='pending_owner'."
                )
            else:
                permission = service.permissions().create(
                    body={"type": "user", "role": "owner",
                          "emailAddress": email},
                    transferOwnership=True, sendNotificationEmail=True,
                    **common,
                ).execute()
                action = "created"

        else:  # reader / commenter / writer
            if existing is not None:
                permission = service.permissions().update(
                    permissionId=existing["id"], body={"role": role}, **common,
                ).execute()
                action = "updated"
            else:
                body = {"type": type, "role": role}
                if type != "anyone":
                    body["emailAddress"] = email
                permission = service.permissions().create(
                    body=body, sendNotificationEmail=False, **common,
                ).execute()
                action = "created"
    except HttpError as e:
        if _reason(e) == "cannotModifyInheritedPermission":
            details = (existing or {}).get("permissionDetails") or []
            inherited_from = next(
                (d.get("inheritedFrom") for d in details
                 if d.get("inherited") and d.get("inheritedFrom")), None)
            raise InheritedPermissionError(file_id, inherited_from) from e
        raise

    return {
        "file_id": file_id,
        "action": action,
        "permission": permission,
        "permissions": _fetch_permissions(service, file_id),
    }


def _fetch_permissions(service, file_id: str) -> list[dict]:
    permissions: list[dict] = []
    page_token = None
    while True:
        page = service.permissions().list(
            fileId=file_id,
            fields=f"permissions({_PERMISSION_FIELDS}), nextPageToken",
            supportsAllDrives=True,
            pageToken=page_token,
        ).execute()
        permissions.extend(page.get("permissions", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            return permissions


def _find_permission(permissions: list[dict], type: str,
                     email: Optional[str]) -> Optional[dict]:
    if type == "anyone":
        return next((p for p in permissions if p.get("type") == "anyone"), None)
    wanted = (email or "").lower()
    return next(
        (p for p in permissions
         if p.get("type") == type
         and (p.get("emailAddress") or "").lower() == wanted),
        None,
    )


def _no_grant(type: str, email: Optional[str]) -> str:
    who = "anyone with the link" if type == "anyone" else f"{type} {email}"
    return f"No grant for {who} on this file; nothing to change."


def _reason(e: HttpError) -> Optional[str]:
    try:
        payload = json.loads(e.content.decode("utf-8"))
        errors = payload.get("error", {}).get("errors") or []
        return errors[0].get("reason") if errors else None
    except Exception:
        return None
