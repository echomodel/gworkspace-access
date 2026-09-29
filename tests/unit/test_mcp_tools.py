"""Tests for ``gwsa.mcp.tools`` — the mcp-app-native tool surface.

Each test sets ``current_user`` on the ContextVar directly (the way
mcp-app's middleware would in a real request) and verifies the tool
function runs end-to-end. The only mocked boundary is the Gmail API
call itself (``gwsa.sdk.mail.list_labels``); everything between the
tool function and the API call — including the credential bridge
in ``gwsa.sdk.auth.get_credentials`` — runs unaltered.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile
from gwsa.mcp.tools.mail import list_email_labels


def _set_user_with_account():
    profile = Profile(
        accounts=[
            GoogleAccount(
                name="personal",
                email="alice@example.com",
                token={
                    "client_id": "user-owned-client",
                    "client_secret": "test-secret",
                    "refresh_token": "test-refresh",
                    "token_uri": "https://oauth2.googleapis.com/token",
                },
            ),
        ],
    )
    user = UserRecord(
        email="alice@example.com",
        profile=profile.model_dump(mode="json"),
    )
    return current_user.set(user)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if asyncio.get_event_loop().is_running() is False \
        else asyncio.new_event_loop().run_until_complete(coro)


def test_list_email_labels_simplifies_sdk_response():
    """Tool reshapes SDK labels into {id, name, type} dicts."""
    tok = _set_user_with_account()
    try:
        sdk_response = [
            {"id": "INBOX",  "name": "INBOX",  "type": "system",
             "messagesTotal": 1234},
            {"id": "Label_1", "name": "Project Phoenix", "type": "user",
             "color": "#abc"},
            {"id": "Label_2", "name": "MissingType"},  # type omitted
        ]
        with patch("gwsa.sdk.mail.list_labels", return_value=sdk_response):
            labels = asyncio.run(list_email_labels())

        assert labels == [
            {"id": "INBOX",   "name": "INBOX",           "type": "system"},
            {"id": "Label_1", "name": "Project Phoenix", "type": "user"},
            {"id": "Label_2", "name": "MissingType",     "type": "user"},
        ]
    finally:
        current_user.reset(tok)


def test_list_email_labels_returns_error_envelope_on_failure():
    """When the SDK raises, the tool returns a single-element error
    list rather than propagating; agents see a structured response."""
    tok = _set_user_with_account()
    try:
        with patch("gwsa.sdk.mail.list_labels",
                   side_effect=RuntimeError("API quota exceeded")):
            result = asyncio.run(list_email_labels())

        assert len(result) == 1
        assert "error" in result[0]
        assert "API quota exceeded" in result[0]["error"]
    finally:
        current_user.reset(tok)


def test_list_email_labels_empty_response():
    tok = _set_user_with_account()
    try:
        with patch("gwsa.sdk.mail.list_labels", return_value=[]):
            result = asyncio.run(list_email_labels())
        assert result == []
    finally:
        current_user.reset(tok)


def test_reply_email_tool_sociable():
    from gwsa.mcp.tools.mail import reply_email
    from tests.unit.test_mail_forward import (
        FakeGmailService,
        _decode_sent,
        _find,
        _raw_of,
        _rich_source,
    )

    tok = _set_user_with_account()  # alice@example.com
    msg = _rich_source()
    del msg["From"]
    del msg["To"]
    msg["From"] = "Sender <sender@example.com>"
    msg["To"] = "Alice <alice@example.com>, Bob <bob@example.com>"
    msg["Cc"] = "Carol <carol@example.com>"
    service = FakeGmailService(_raw_of(msg))

    try:
        with patch("gwsa.sdk.mail.service.build", return_value=service):
            result = asyncio.run(
                reply_email(
                    message_id="orig-id",
                    body="Plain reply text.",
                    html_body="<h1>HTML Reply</h1>",
                    as_draft=True,
                )
            )

        assert result["success"] is True
        assert result["is_draft"] is True
        assert result["id"] == "draft-1"
        assert result["thread_id"] == "thread-1"
        assert "sender@example.com" in result["to"]
        assert "bob@example.com" in result["to"]
        assert "carol@example.com" in (result["cc"] or "")

        sent = _decode_sent(service.sent[0])
        html = _find(sent, "text/html")
        assert html is not None
        assert "<h1>HTML Reply</h1>" in html.get_content()
        assert "sender@example.com" in sent["To"]
        assert "bob@example.com" in sent["To"]
        assert "alice@example.com" not in sent["To"]
        assert "carol@example.com" in sent["Cc"]
    finally:
        current_user.reset(tok)


def test_email_tools_allow_html_body_without_plain_body():
    """Calling create_email_draft, send_email, or reply_email with only
    html_body (omitting body) succeeds and emits valid text/html content."""
    from gwsa.mcp.tools.mail import create_email_draft, reply_email, send_email
    from tests.unit.test_mail_forward import (
        FakeGmailService,
        _decode_sent,
        _find,
        _raw_of,
        _rich_source,
    )

    tok = _set_user_with_account()
    service = FakeGmailService(_raw_of(_rich_source()))

    try:
        with patch("gwsa.sdk.mail.service.build", return_value=service):
            draft_res = asyncio.run(
                create_email_draft(
                    to="bob@example.com",
                    subject="HTML-only Draft",
                    html_body="<p>Hello <b>Bob</b></p>",
                )
            )
            send_res = asyncio.run(
                send_email(
                    to="bob@example.com",
                    subject="HTML-only Send",
                    html_body="<p>Sent <b>HTML</b></p>",
                )
            )
            reply_res = asyncio.run(
                reply_email(
                    message_id="orig-id",
                    html_body="<p>Reply <b>HTML</b></p>",
                    as_draft=True,
                )
            )

        assert draft_res["success"] is True
        assert send_res["success"] is True
        assert reply_res["success"] is True

        draft_mime = _decode_sent(service.sent[0])
        assert "<p>Hello <b>Bob</b></p>" in _find(draft_mime, "text/html").get_content()

        send_mime = _decode_sent(service.sent[1])
        assert "<p>Sent <b>HTML</b></p>" in _find(send_mime, "text/html").get_content()

        reply_mime = _decode_sent(service.sent[2])
        assert "<p>Reply <b>HTML</b></p>" in _find(reply_mime, "text/html").get_content()
    finally:
        current_user.reset(tok)


def test_reply_and_forward_email_default_to_draft():
    """MCP tools reply_email and forward_email must default to as_draft=True
    so omitting as_draft safely creates a Gmail draft instead of sending live."""
    from gwsa.mcp.tools.mail import forward_email, reply_email
    from tests.unit.test_mail_forward import (
        FakeGmailService,
        _raw_of,
        _rich_source,
    )

    tok = _set_user_with_account()
    service = FakeGmailService(_raw_of(_rich_source()))

    try:
        with patch("gwsa.sdk.mail.service.build", return_value=service):
            reply_res = asyncio.run(
                reply_email(
                    message_id="orig-id",
                    body="Safe default reply draft.",
                )
            )
            fwd_res = asyncio.run(
                forward_email(
                    message_id="orig-id",
                    to="bob@example.com",
                    note="Safe default forward draft.",
                )
            )

        assert reply_res["success"] is True
        assert reply_res["is_draft"] is True
        assert reply_res["id"] == "draft-1"
        assert fwd_res["success"] is True
        assert fwd_res["is_draft"] is True
        assert fwd_res["id"] == "draft-1"
        assert len(service.drafts_obj.created_bodies) == 2
    finally:
        current_user.reset(tok)
