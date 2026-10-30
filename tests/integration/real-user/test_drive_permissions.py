"""Integration tests for Drive sharing (``list_permissions`` /
``set_permission``) against the live API.

Self-contained: uploads a scratch file, reads its grants, turns link
sharing on and off, and trashes the file. Ownership transfer needs two
accounts and a human accepting an invitation, so it is not exercised
here; the unit tests pin the calls it makes.

Covers:
- ``list_permissions`` returns the owner's grant as the API gives it
- ``set_permission(type="anyone")`` creates and deletes the link grant,
  and the returned ``permissions`` list reflects each change
- ``none`` on the owner's own grant is refused before any API call
"""

from __future__ import annotations

import time

import pytest

from gwsa.sdk import drive
from gwsa.sdk.drive.permissions import OwnerRemovalRefusedError


def _unique(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _safe_trash(file_id: str) -> None:
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


@pytest.mark.integration
def test_link_sharing_on_and_off_and_owner_grant_is_kept():
    uploaded = drive.upload_bytes(
        data=b"sharing test\n", name=_unique("gwsa-it-perms") + ".txt",
        mime_type="text/plain",
    )
    file_id = uploaded.get("id")
    assert file_id, f"upload_bytes returned no id: {uploaded}"
    try:
        listed = drive.list_permissions(file_id)
        owners = [p for p in listed["permissions"] if p["role"] == "owner"]
        assert len(owners) == 1, listed
        owner_email = owners[0]["emailAddress"]
        assert not any(p["type"] == "anyone" for p in listed["permissions"])

        on = drive.set_permission(file_id, role="reader", type="anyone")
        assert on["action"] == "created"
        assert on["permission"]["type"] == "anyone"
        assert any(p["type"] == "anyone" and p["role"] == "reader"
                   for p in on["permissions"])

        with pytest.raises(OwnerRemovalRefusedError):
            drive.set_permission(file_id, role="none", email=owner_email)

        off = drive.set_permission(file_id, role="none", type="anyone")
        assert off["action"] == "deleted"
        assert off["permission"] is None
        assert not any(p["type"] == "anyone" for p in off["permissions"])
    finally:
        _safe_trash(file_id)
