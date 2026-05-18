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
