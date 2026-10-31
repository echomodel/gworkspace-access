"""Unit tests for Drive sharing: ``list_permissions`` / ``set_permission``
and the ``drive_list_permissions`` / ``drive_set_permission`` tools.

Sociable style: the current user and account are real profile objects,
credential resolution runs unaltered, and only the Drive API service is
mocked. Each test pins which ``permissions`` call ``set_permission``
makes for a role, and with which body and flags.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError
from mcp_app.app import _discover_tools
from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile, app
from gwsa.cli.drive_commands import drive_group
from gwsa.mcp.tools.drive import drive_list_permissions, drive_set_permission
from gwsa.sdk import drive
from gwsa.sdk.drive.permissions import (
    InheritedPermissionError,
    OwnerRemovalRefusedError,
    PermissionNotFoundError,
)

ME = "alice@example.com"
OWNER_GRANT = {"id": "p-owner", "type": "user", "emailAddress": ME,
               "role": "owner"}
BOB_WRITER = {"id": "p-bob", "type": "user", "emailAddress": "bob@example.com",
              "role": "writer"}
ANYONE_READER = {"id": "anyoneWithLink", "type": "anyone", "role": "reader"}


@pytest.fixture
def user():
    profile = Profile(accounts=[GoogleAccount(
        name="personal", email=ME,
        token={"client_id": "c", "client_secret": "s", "refresh_token": "r",
               "token_uri": "https://oauth2.googleapis.com/token"},
    )])
    tok = current_user.set(UserRecord(email=ME, profile=profile.model_dump(mode="json")))
    yield
    current_user.reset(tok)


def _service(grants: list[dict], after: list[dict] | None = None):
    """A Drive service whose ``permissions.list`` returns ``grants`` first
    and ``after`` (default: the same) on the verification read."""
    svc = MagicMock()
    perms = svc.permissions.return_value
    perms.list.return_value.execute.side_effect = [
        {"permissions": grants}, {"permissions": after if after is not None else grants},
    ]
    for op in ("create", "update"):
        getattr(perms, op).return_value.execute.side_effect = (
            lambda *a, **k: {"id": "p-new", "role": "x"})
    perms.delete.return_value.execute.return_value = ""
    return svc


def _patched(svc):
    return patch("gwsa.sdk.drive.permissions.get_drive_service", return_value=svc)


def _http_error(status: int, reason: str) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = "Forbidden"
    content = json.dumps({"error": {"code": status, "message": reason,
                                    "errors": [{"reason": reason}]}}).encode()
    return HttpError(resp, content)


# --- list_permissions --------------------------------------------------


def test_list_permissions_returns_api_records_across_pages(user):
    svc = MagicMock()
    svc.permissions.return_value.list.return_value.execute.side_effect = [
        {"permissions": [OWNER_GRANT], "nextPageToken": "t2"},
        {"permissions": [BOB_WRITER]},
    ]
    with _patched(svc):
        result = drive.list_permissions("f1")
    assert result == {"file_id": "f1", "permissions": [OWNER_GRANT, BOB_WRITER]}
    calls = svc.permissions.return_value.list.call_args_list
    assert calls[0].kwargs["pageToken"] is None
    assert calls[1].kwargs["pageToken"] == "t2"
    assert "permissionDetails(inherited, inheritedFrom" in calls[0].kwargs["fields"]
    assert calls[0].kwargs["supportsAllDrives"] is True


# --- set_permission: reader / commenter / writer -----------------------


def test_new_grant_is_created_without_notification(user):
    svc = _service([OWNER_GRANT], after=[OWNER_GRANT, BOB_WRITER])
    with _patched(svc):
        result = drive.set_permission("f1", role="writer", email="bob@example.com")
    create = svc.permissions.return_value.create
    create.assert_called_once()
    assert create.call_args.kwargs["body"] == {
        "type": "user", "role": "writer", "emailAddress": "bob@example.com"}
    assert create.call_args.kwargs["sendNotificationEmail"] is False
    svc.permissions.return_value.update.assert_not_called()
    assert result["action"] == "created"
    assert result["permissions"] == [OWNER_GRANT, BOB_WRITER]


def test_existing_grant_is_lowered_by_update(user):
    svc = _service([OWNER_GRANT, BOB_WRITER])
    with _patched(svc):
        result = drive.set_permission("f1", role="reader", email="Bob@Example.com")
    update = svc.permissions.return_value.update
    update.assert_called_once()
    assert update.call_args.kwargs["permissionId"] == "p-bob"
    assert update.call_args.kwargs["body"] == {"role": "reader"}
    svc.permissions.return_value.create.assert_not_called()
    assert result["action"] == "updated"


def test_group_grant_uses_group_type(user):
    svc = _service([OWNER_GRANT])
    with _patched(svc):
        drive.set_permission("f1", role="reader", email="team@example.com", type="group")
    body = svc.permissions.return_value.create.call_args.kwargs["body"]
    assert body == {"type": "group", "role": "reader", "emailAddress": "team@example.com"}


# --- set_permission: none ----------------------------------------------


def test_none_deletes_the_grant(user):
    svc = _service([OWNER_GRANT, BOB_WRITER], after=[OWNER_GRANT])
    with _patched(svc):
        result = drive.set_permission("f1", role="none", email="bob@example.com")
    delete = svc.permissions.return_value.delete
    delete.assert_called_once_with(fileId="f1", permissionId="p-bob",
                                   supportsAllDrives=True)
    assert result["action"] == "deleted"
    assert result["permission"] is None
    assert result["permissions"] == [OWNER_GRANT]


def test_none_without_a_grant_is_refused(user):
    svc = _service([OWNER_GRANT])
    with _patched(svc), pytest.raises(PermissionNotFoundError, match="bob@example.com"):
        drive.set_permission("f1", role="none", email="bob@example.com")
    svc.permissions.return_value.delete.assert_not_called()


def test_none_on_the_owner_grant_is_refused(user):
    svc = _service([OWNER_GRANT])
    with _patched(svc), pytest.raises(OwnerRemovalRefusedError, match="pending_owner"):
        drive.set_permission("f1", role="none", email=ME)
    svc.permissions.return_value.delete.assert_not_called()


# --- set_permission: anyone (link sharing) -----------------------------


def test_anyone_reader_turns_link_sharing_on(user):
    svc = _service([OWNER_GRANT], after=[OWNER_GRANT, ANYONE_READER])
    with _patched(svc):
        result = drive.set_permission("f1", role="reader", type="anyone")
    body = svc.permissions.return_value.create.call_args.kwargs["body"]
    assert body == {"type": "anyone", "role": "reader"}
    assert result["action"] == "created"


def test_anyone_none_turns_link_sharing_off(user):
    svc = _service([OWNER_GRANT, ANYONE_READER], after=[OWNER_GRANT])
    with _patched(svc):
        result = drive.set_permission("f1", role="none", type="anyone")
    assert svc.permissions.return_value.delete.call_args.kwargs["permissionId"] == "anyoneWithLink"
    assert result["action"] == "deleted"


def test_anyone_rejects_email_and_ownership(user):
    with pytest.raises(ValueError, match="no email"):
        drive.set_permission("f1", role="reader", type="anyone", email="x@example.com")
    with pytest.raises(ValueError, match="needs a user"):
        drive.set_permission("f1", role="pending_owner", type="anyone")


# --- set_permission: ownership transfer --------------------------------


def test_pending_owner_on_existing_grant_updates_it(user):
    svc = _service([OWNER_GRANT, BOB_WRITER])
    with _patched(svc):
        result = drive.set_permission("f1", role="pending_owner", email="bob@example.com")
    update = svc.permissions.return_value.update
    assert update.call_args.kwargs["permissionId"] == "p-bob"
    assert update.call_args.kwargs["body"] == {"role": "writer", "pendingOwner": True}
    assert result["action"] == "updated"


def test_pending_owner_on_new_grant_creates_with_notification(user):
    svc = _service([OWNER_GRANT])
    with _patched(svc):
        drive.set_permission("f1", role="pending_owner", email="bob@example.com")
    create = svc.permissions.return_value.create
    assert create.call_args.kwargs["body"] == {
        "type": "user", "role": "writer", "emailAddress": "bob@example.com",
        "pendingOwner": True}
    assert create.call_args.kwargs["sendNotificationEmail"] is True


def test_owner_accepts_on_the_callers_own_grant(user):
    mine = {"id": "p-me", "type": "user", "emailAddress": ME, "role": "writer",
            "pendingOwner": True}
    svc = _service([{**BOB_WRITER, "role": "owner"}, mine])
    with _patched(svc):
        result = drive.set_permission("f1", role="owner")
    update = svc.permissions.return_value.update
    assert update.call_args.kwargs["permissionId"] == "p-me"
    assert update.call_args.kwargs["body"] == {"role": "owner"}
    assert update.call_args.kwargs["transferOwnership"] is True
    assert result["action"] == "updated"


def test_owner_with_no_grant_to_accept_is_refused(user):
    svc = _service([{**BOB_WRITER, "role": "owner"}])
    with _patched(svc), pytest.raises(PermissionNotFoundError, match="no pending transfer"):
        drive.set_permission("f1", role="owner")


def test_owner_with_email_transfers_directly(user):
    svc = _service([OWNER_GRANT, BOB_WRITER])
    with _patched(svc):
        drive.set_permission("f1", role="owner", email="bob@example.com")
    update = svc.permissions.return_value.update
    assert update.call_args.kwargs["permissionId"] == "p-bob"
    assert update.call_args.kwargs["transferOwnership"] is True


# --- set_permission: validation and API rejections ---------------------


def test_unknown_role_and_type_are_rejected(user):
    with pytest.raises(ValueError, match="Unknown role"):
        drive.set_permission("f1", role="editor", email="bob@example.com")
    with pytest.raises(ValueError, match="Unknown type"):
        drive.set_permission("f1", role="reader", email="bob@example.com", type="domain")
    with pytest.raises(ValueError, match="needs an email"):
        drive.set_permission("f1", role="reader")


def test_inherited_grant_rejection_names_the_folder(user):
    inherited = {**BOB_WRITER, "permissionDetails": [
        {"inherited": True, "inheritedFrom": "folder-9", "role": "writer"}]}
    svc = _service([OWNER_GRANT, inherited])
    svc.permissions.return_value.delete.return_value.execute.side_effect = (
        _http_error(403, "cannotModifyInheritedPermission"))
    with _patched(svc), pytest.raises(InheritedPermissionError) as info:
        drive.set_permission("f1", role="none", email="bob@example.com")
    assert info.value.inherited_from == "folder-9"
    assert "folder-9" in str(info.value)


def test_other_api_rejections_propagate(user):
    svc = _service([OWNER_GRANT])
    svc.permissions.return_value.create.return_value.execute.side_effect = (
        _http_error(403, "insufficientFilePermissions"))
    with _patched(svc), pytest.raises(HttpError):
        drive.set_permission("f1", role="reader", email="bob@example.com")


# --- MCP tools -----------------------------------------------------------


def test_tools_are_registered_on_both_transports():
    for transport in ("http", "stdio"):
        names = {f.__name__ for f in _discover_tools(app._discovered_modules, transport)}
        assert {"drive_list_permissions", "drive_set_permission"} <= names


def test_drive_list_permissions_tool_delegates(user):
    with patch("gwsa.sdk.drive.list_permissions",
               return_value={"file_id": "f1", "permissions": [OWNER_GRANT]}) as p:
        result = asyncio.run(drive_list_permissions("f1", account="personal"))
    p.assert_called_once_with("f1", account="personal")
    assert result["permissions"] == [OWNER_GRANT]


def test_drive_set_permission_tool_delegates(user):
    sdk_result = {"file_id": "f1", "action": "updated", "permission": BOB_WRITER,
                  "permissions": [OWNER_GRANT, BOB_WRITER]}
    with patch("gwsa.sdk.drive.set_permission", return_value=sdk_result) as p:
        result = asyncio.run(drive_set_permission(
            "f1", role="writer", email="bob@example.com", account="personal"))
    p.assert_called_once_with("f1", role="writer", email="bob@example.com",
                              type="user", account="personal")
    assert result == sdk_result


def test_drive_set_permission_tool_envelopes_refusals(user):
    svc = _service([OWNER_GRANT])
    with _patched(svc):
        result = asyncio.run(drive_set_permission("f1", role="none", email=ME))
    assert "error" in result
    assert "pending_owner" in result["error"]


def test_drive_set_permission_tool_envelopes_api_rejection(user):
    with patch("gwsa.sdk.drive.set_permission",
               side_effect=_http_error(403, "insufficientFilePermissions")):
        result = asyncio.run(drive_set_permission("f1", role="reader", email="b@example.com"))
    assert "Drive rejected" in result["error"]
    assert "insufficientFilePermissions" in result["details"]
    assert "account" in result["hint"]


# --- CLI -----------------------------------------------------------------


def test_cli_permissions_set_passes_role_email_and_type():
    sdk_result = {"file_id": "f1", "action": "created", "permission": ANYONE_READER,
                  "permissions": [OWNER_GRANT, ANYONE_READER]}
    with patch("gwsa.sdk.drive.set_permission", return_value=sdk_result) as p:
        res = CliRunner().invoke(drive_group, ["permissions", "set", "f1", "reader",
                                               "--type", "anyone"])
    assert res.exit_code == 0, res.output
    p.assert_called_once_with("f1", role="reader", email=None, type="anyone")
    assert json.loads(res.output)["action"] == "created"


def test_cli_permissions_set_rejects_unknown_role():
    res = CliRunner().invoke(drive_group, ["permissions", "set", "f1", "editor"])
    assert res.exit_code != 0
    assert "editor" in res.output


def test_cli_permissions_list_prints_json():
    with patch("gwsa.sdk.drive.list_permissions",
               return_value={"file_id": "f1", "permissions": [OWNER_GRANT]}):
        res = CliRunner().invoke(drive_group, ["permissions", "list", "f1"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["permissions"] == [OWNER_GRANT]
