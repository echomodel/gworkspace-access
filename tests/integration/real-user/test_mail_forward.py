"""Integration test for forwarding a message.

Creates a draft (a real message we own), forwards it as a draft so
nothing is actually sent, then reads the forwarded message back and
verifies the ``Fwd:`` subject and that the original body is carried
into the forward. Attachment / inline-image byte fidelity is covered
exhaustively by the offline unit tests; this test confirms the live
``messages.get?format=raw`` rebuild path works against the real API.
"""

import pytest
from mcp_app.context import current_user

from gwsa.sdk.mail import (
    create_draft,
    forward_message,
    get_gmail_service,
    read_message,
    reply_message,
)


def _self_email() -> str:
    user = current_user.get()
    profile = user.profile
    accounts = getattr(profile, "accounts", None) or []
    default_name = getattr(profile, "default_account", None)
    chosen = next(
        (a for a in accounts if a.name == default_name),
        accounts[0] if accounts else None,
    )
    return chosen.email if chosen else "me"


def _safe_delete_draft(draft_id: str | None) -> None:
    if not draft_id:
        return
    try:
        get_gmail_service().users().drafts().delete(
            userId="me", id=draft_id
        ).execute()
    except Exception:
        pass


@pytest.mark.integration
def test_forward_draft_preserves_subject_and_body():
    email_address = _self_email()
    unique = "forward-integration-marker-9f3a"

    draft = create_draft(
        to=email_address,
        subject="Forward Source Message",
        body=f"Original body. {unique}",
        html_body=f"<p>Original body. {unique}</p>",
    )
    source_draft_id = draft.get("id")
    forward_draft_id = None
    try:
        source_message_id = draft.get("message", {}).get("id")
        assert source_message_id, "Draft did not return an inner message id."

        result = forward_message(
            message_id=source_message_id,
            to=email_address,
            note="Forwarding for your records.",
            as_draft=True,
        )
        forward_draft_id = result.get("id")
        forwarded_message_id = result.get("message", {}).get("id")
        assert result["is_draft"] is True
        assert forwarded_message_id, "Forward draft did not return a message id."

        msg = read_message(forwarded_message_id)
        assert msg.get("subject") == "Fwd: Forward Source Message"

        body = msg.get("body", {})
        text = body.get("text") or ""
        assert "Forwarding for your records." in text
        assert "Forwarded message" in text
        assert unique in text
    finally:
        _safe_delete_draft(forward_draft_id)
        _safe_delete_draft(source_draft_id)


@pytest.mark.integration
def test_reply_draft_preserves_thread_quote_and_recipients():
    email_address = _self_email()
    unique = "reply-integration-marker-7b2c"

    draft = create_draft(
        to=email_address,
        cc="colleague@example.com",
        subject="Reply Source Message",
        body=f"Original thread body. {unique}",
        html_body=f"<p>Original thread body. {unique}</p>",
    )
    source_draft_id = draft.get("id")
    reply_draft_id = None
    try:
        source_message_id = draft.get("message", {}).get("id")
        assert source_message_id, "Draft did not return an inner message id."

        source_msg = read_message(source_message_id)
        source_thread_id = source_msg.get("threadId")
        assert source_thread_id, "Source message did not have a threadId."
        assert "colleague@example.com" in (source_msg.get("cc") or "")

        result = reply_message(
            reply_to_message_id=source_message_id,
            body="Follow-up reply note.",
            as_draft=True,
        )
        reply_draft_id = result.get("id")
        reply_message_id = result.get("message", {}).get("id")
        assert result["is_draft"] is True
        assert result["threadId"] == source_thread_id
        assert reply_message_id, "Reply draft did not return a message id."

        reply_msg = read_message(reply_message_id)
        assert reply_msg.get("threadId") == source_thread_id
        assert reply_msg.get("subject") == "Re: Reply Source Message"
        assert "colleague@example.com" in (reply_msg.get("cc") or "")

        text = reply_msg.get("body", {}).get("text") or ""
        assert "Follow-up reply note." in text
        assert unique in text
    finally:
        _safe_delete_draft(reply_draft_id)
        _safe_delete_draft(source_draft_id)
