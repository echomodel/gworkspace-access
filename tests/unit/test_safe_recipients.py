"""Sociable unit tests for safe recipient resolution and send_safe_email operations.

Follows the sociable testing philosophy: exercises full transactions through
the SDK and MCP layers end-to-end with real MIME construction and header validation.
Environment variables are managed via pytest's monkeypatch fixture, and the only
seam is the external Google API service boundary.
"""

from __future__ import annotations

import asyncio
import base64
import email
from email import policy
import pytest

from mcp_app.context import current_user
from mcp_app.models import UserRecord

from gwsa import GoogleAccount, Profile
from gwsa.sdk.mail.safe_recipients import (
    get_safe_recipients,
    resolve_safe_recipient,
    send_safe_message,
    UnapprovedRecipientError,
)
from gwsa.mcp.tools.mail import list_safe_recipients, send_safe_email


# --- Fake Gmail API Boundary ------------------------------------------------


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeGmailService:
    """Minimal fake for the external Gmail API boundary."""

    def __init__(self):
        self.sent_messages: list[dict] = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId: str, body: dict):
        self.sent_messages.append(body)
        return _Exec({
            "id": f"msg-{len(self.sent_messages)}",
            "threadId": f"thread-{len(self.sent_messages)}",
            "labelIds": ["SENT"],
        })


@pytest.fixture
def fake_gmail(monkeypatch):
    """Provide a fake Gmail service at the external API boundary."""
    import sys
    service = _FakeGmailService()
    send_module = sys.modules["gwsa.sdk.mail.send"]
    monkeypatch.setattr(send_module, "get_gmail_service", lambda account=None: service)
    return service


@pytest.fixture
def active_user():
    """Set up an active mcp-app user record with personal and work accounts."""
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
            GoogleAccount(
                name="work",
                email="alice.corp@example.com",
                token={
                    "client_id": "user-owned-client",
                    "client_secret": "test-secret",
                    "refresh_token": "test-refresh",
                    "token_uri": "https://oauth2.googleapis.com/token",
                },
            ),
        ],
        default_account="personal",
    )
    user = UserRecord(
        email="alice@example.com",
        profile=profile.model_dump(mode="json"),
    )
    tok = current_user.set(user)
    try:
        yield user
    finally:
        current_user.reset(tok)


# --- Sociable Tests: Resolution & Environment -------------------------------


def test_get_safe_recipients_default_active_account(active_user, monkeypatch):
    """Without env vars, only 'me' and 'self' (active account) are available."""
    monkeypatch.delenv("GWSA_SAFE_RECIPIENTS", raising=False)
    monkeypatch.delenv("SAFE_RECIPIENTS", raising=False)

    recipients = get_safe_recipients()
    assert recipients == {"me": "alice@example.com", "self": "alice@example.com"}
    # Other accounts on the profile are not auto-added
    assert "work" not in recipients
    assert "personal" not in recipients


def test_get_safe_recipients_from_env_comma_separated(active_user, monkeypatch):
    """GWSA_SAFE_RECIPIENTS parses comma-separated key=value pairs."""
    env_val = "notes=notes@example.org, my-phone=1234567890@sms.example.org, ME=custom.me@example.com"
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", env_val)

    recipients = get_safe_recipients()
    assert recipients["notes"] == "notes@example.org"
    assert recipients["my-phone"] == "1234567890@sms.example.org"
    assert recipients["me"] == "custom.me@example.com"


def test_get_safe_recipients_from_env_json(active_user, monkeypatch):
    """GWSA_SAFE_RECIPIENTS parses JSON string."""
    env_val = '{"alert": "alerts@example.com", "pager": "pager@example.com"}'
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", env_val)

    recipients = get_safe_recipients()
    assert recipients["alert"] == "alerts@example.com"
    assert recipients["pager"] == "pager@example.com"
    assert recipients["me"] == "alice@example.com"


def test_get_safe_recipients_fallback_env_name(active_user, monkeypatch):
    """SAFE_RECIPIENTS is honored if GWSA_SAFE_RECIPIENTS is not set."""
    monkeypatch.delenv("GWSA_SAFE_RECIPIENTS", raising=False)
    monkeypatch.setenv("SAFE_RECIPIENTS", "backup=backup@example.com")

    recipients = get_safe_recipients()
    assert recipients["backup"] == "backup@example.com"


def test_resolve_safe_recipient_by_alias(active_user, monkeypatch):
    """Alias resolution is case-insensitive."""
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", "notes=notes@example.com")

    assert resolve_safe_recipient("notes") == "notes@example.com"
    assert resolve_safe_recipient("NOTES") == "notes@example.com"
    assert resolve_safe_recipient("me") == "alice@example.com"


def test_resolve_safe_recipient_by_exact_email(active_user, monkeypatch):
    """Passing the exact email of an approved safe recipient is also accepted."""
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", "notes=notes@example.com")

    assert resolve_safe_recipient("notes@example.com") == "notes@example.com"
    assert resolve_safe_recipient("alice@example.com") == "alice@example.com"


def test_resolve_safe_recipient_rejects_unapproved(active_user, monkeypatch):
    """Unapproved recipient raises UnapprovedRecipientError with allowed list."""
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", "notes=notes@example.com")

    with pytest.raises(UnapprovedRecipientError) as exc_info:
        resolve_safe_recipient("unauthorized@example.com")

    err_msg = str(exc_info.value)
    assert "unauthorized@example.com" in err_msg
    assert "notes" in err_msg
    assert "me" in err_msg


# --- Sociable Tests: Full Transaction Execution (Real MIME Assembly) --------


def test_send_safe_message_full_transaction(active_user, fake_gmail, monkeypatch):
    """send_safe_message executes real MIME assembly and delivers to the fake API."""
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", "notes=notes@example.com")

    result = send_safe_message(
        recipient="notes",
        subject="Status update",
        body="Plain body text",
        html_body="<p>HTML body text</p>",
        account="personal",
    )

    assert result["resolved_to"] == "notes@example.com"
    assert len(fake_gmail.sent_messages) == 1

    # Decode and inspect the raw RFC 2822 MIME message that was constructed
    raw_encoded = fake_gmail.sent_messages[0]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_encoded)
    parsed_msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    assert parsed_msg["To"] == "notes@example.com"
    assert parsed_msg["Subject"] == "Status update"
    assert parsed_msg.is_multipart()


def test_send_safe_message_blocks_unapproved_before_api(active_user, fake_gmail, monkeypatch):
    """send_safe_message aborts before touching the API when recipient is unapproved."""
    monkeypatch.delenv("GWSA_SAFE_RECIPIENTS", raising=False)
    monkeypatch.delenv("SAFE_RECIPIENTS", raising=False)

    with pytest.raises(UnapprovedRecipientError):
        send_safe_message(recipient="stranger@example.com", subject="Blocked")

    # Verify no message reached the API
    assert len(fake_gmail.sent_messages) == 0


# --- Sociable Tests: MCP Tool Surface ---------------------------------------


def test_mcp_list_safe_recipients(active_user, monkeypatch):
    """list_safe_recipients tool returns dictionary of aliases."""
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", "phone=123@sms.example.org")

    res = asyncio.run(list_safe_recipients())
    assert "safe_recipients" in res
    assert res["safe_recipients"]["phone"] == "123@sms.example.org"
    assert "phone" in res["aliases"]
    assert "me" in res["aliases"]


def test_mcp_send_safe_email_success(active_user, fake_gmail, monkeypatch):
    """send_safe_email MCP tool runs full transaction and returns structured result."""
    monkeypatch.setenv("GWSA_SAFE_RECIPIENTS", "phone=123@sms.example.org")

    res = asyncio.run(send_safe_email(
        recipient="phone",
        subject="Alert",
        body="Everything OK",
    ))

    assert res["success"] is True
    assert res["resolved_email"] == "123@sms.example.org"
    assert len(fake_gmail.sent_messages) == 1


def test_mcp_send_safe_email_rejected_without_crash(active_user, fake_gmail, monkeypatch):
    """send_safe_email MCP tool gracefully catches unapproved recipient errors."""
    monkeypatch.delenv("GWSA_SAFE_RECIPIENTS", raising=False)
    monkeypatch.delenv("SAFE_RECIPIENTS", raising=False)

    res = asyncio.run(send_safe_email(
        recipient="attacker@example.com",
        subject="Test",
        body="Click here",
    ))

    assert res["success"] is False
    assert "attacker@example.com" in res["error"]
    assert "not an approved safe recipient" in res["error"]
    assert len(fake_gmail.sent_messages) == 0
