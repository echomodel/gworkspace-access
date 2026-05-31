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

from gwsa.sdk.mail import create_draft, forward_message, read_message


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
    source_message_id = draft.get("message", {}).get("id")
    assert source_message_id, "Draft did not return an inner message id."

    result = forward_message(
        message_id=source_message_id,
        to=email_address,
        note="Forwarding for your records.",
        as_draft=True,
    )
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
