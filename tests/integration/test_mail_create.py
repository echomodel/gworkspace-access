"""
Integration tests for creating draft emails.
"""

import pytest
from gwsa.sdk.mail import create_draft, read_message
from gwsa.sdk.profiles import get_active_profile


@pytest.mark.integration
def test_create_html_draft_email():
    """
    Test creating a draft email with both plain text and HTML bodies,
    and verify the content was created properly by reading it back.
    """
    profile = get_active_profile()
    # Fallback to "me" if active profile doesn't have an email bound
    email_address = profile.get("email") if profile else "me"
    
    plain_text = "This is a plain text draft for integration testing."
    html_text = "<b>This is an HTML draft</b> for <i>integration testing</i>."
    subject_text = "Integration Test HTML Draft"

    # Step 1: Create the draft
    draft_result = create_draft(
        to=email_address,
        subject=subject_text,
        body=plain_text,
        html_body=html_text,
    )

    assert draft_result.get("id"), "Draft creation failed, no draft ID returned."
    
    # Drafts contain a fully formed message inside them with its own ID
    message_id = draft_result.get("message", {}).get("id")
    assert message_id, "Draft creation failed to return a message ID."

    # Step 2: Read the newly created message to verify contents
    msg = read_message(message_id)

    # Validate fields
    assert msg.get("subject") == subject_text
    
    body = msg.get("body", {})
    
    # Verify the plain text part is present
    assert body.get("text") is not None, "Plain text body is missing."
    assert plain_text in body.get("text"), "Plain text body did not match the input."
    
    # Verify the HTML part is present
    assert body.get("html") is not None, "HTML body is missing."
    assert html_text in body.get("html"), "HTML body did not match the input."
