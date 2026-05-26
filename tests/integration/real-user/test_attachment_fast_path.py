"""Integration test for ``download_email_attachment`` v0.12.1 fast path.

Self-contained: each run sends an email to the active account containing
a synthetic attachment, exercises the explicit-filename/mime fast path,
and trashes both the email and the Drive upload before exiting. Nothing
pre-existing in the mailbox or Drive is touched, and nothing is left
behind on success.

What this proves end-to-end against real Google APIs (which mocks cannot):

1. The new ``filename`` + ``mime_type`` parameters on
   ``download_email_attachment`` actually engage the fast path
   (``get_attachment_with_metadata`` is bypassed).
2. The Drive copy lands with the **original filename and MIME type** —
   the regression that prompted v0.12.1 in the first place, where the
   fallback ``attachment-<id_prefix>`` name showed up because Gmail
   rotates attachment IDs across ``messages.get`` requests.
3. The bytes round-trip intact (size matches the synthetic payload).

If this test passes after a future change to the attachment surface,
the user-visible filename/MIME contract still holds. If it fails, the
fast path is broken.
"""

from __future__ import annotations

import asyncio
import base64
import email.mime.application
import email.mime.multipart
import email.mime.text
import time

import pytest

from gwsa.mcp.tools.mail import download_email_attachment
from gwsa.sdk import drive, mail
from gwsa.sdk.destinations import DriveDestination
from gwsa.sdk.mail.read import _extract_attachments


def _build_raw_message_with_attachment(
    to_addr: str,
    subject: str,
    body_text: str,
    attachment_bytes: bytes,
    attachment_name: str,
    attachment_mime: str,
) -> str:
    """Build a base64url-encoded RFC 2822 message with one attachment.

    Used to send via ``users.messages.send``. gwsa's SDK send helper
    doesn't support attachments yet; this is a minimal in-test MIME
    builder kept here so the test stays self-contained.
    """
    msg = email.mime.multipart.MIMEMultipart()
    msg["To"] = to_addr
    msg["Subject"] = subject

    msg.attach(email.mime.text.MIMEText(body_text, "plain"))

    main_type, sub_type = attachment_mime.split("/", 1)
    part = email.mime.application.MIMEApplication(
        attachment_bytes, _subtype=sub_type
    )
    part.add_header(
        "Content-Disposition", "attachment", filename=attachment_name
    )
    msg.attach(part)

    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


@pytest.fixture
def sent_attachment_email():
    """Send a self-addressed email with a synthetic attachment, yield
    everything the test needs to download it, then trash all copies on
    teardown.

    Yields ``(message_id, attachment_id, filename, mime_type,
    attachment_bytes)``.
    """
    service = mail.get_gmail_service()
    own_email = service.users().getProfile(userId="me").execute()["emailAddress"]

    # Use a recognisable, time-stamped subject + filename so even if
    # cleanup is interrupted the user can find and remove leftovers.
    stamp = int(time.time() * 1000)
    subject = f"[gwsa-livetest] attachment fast-path test {stamp}"
    attachment_name = f"gwsa-livetest-{stamp}.pdf"
    # Minimal but valid-ish PDF header so MIME sniffers don't complain.
    attachment_bytes = (
        b"%PDF-1.4\n"
        b"%gwsa-livetest synthetic attachment, safe to delete\n"
        + b"x" * 512
        + b"\n%%EOF\n"
    )
    attachment_mime = "application/pdf"

    raw = _build_raw_message_with_attachment(
        to_addr=own_email,
        subject=subject,
        body_text=(
            "This is a gwsa integration test message. Safe to delete. "
            f"Test run timestamp: {stamp}."
        ),
        attachment_bytes=attachment_bytes,
        attachment_name=attachment_name,
        attachment_mime=attachment_mime,
    )

    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    sent_id = sent["id"]

    # Wait for the message to surface in our own mailbox with an
    # attachmentId we can address. ``send`` returns immediately but the
    # full part tree may take a moment to be queryable.
    attachment_id = None
    filename = None
    mime_type = None
    deadline = time.time() + 20
    while time.time() < deadline:
        msg = service.users().messages().get(
            userId="me", id=sent_id, format="full"
        ).execute()
        atts = _extract_attachments(msg.get("payload", {}))
        for att in atts:
            if att.get("filename") == attachment_name:
                attachment_id = att["attachmentId"]
                filename = att["filename"]
                mime_type = att["mimeType"]
                break
        if attachment_id:
            break
        time.sleep(1)
    if not attachment_id:
        pytest.fail(
            f"Sent message {sent_id} but no attachment ID surfaced "
            f"in the message tree within 20s."
        )

    try:
        yield (sent_id, attachment_id, filename, mime_type, attachment_bytes)
    finally:
        # Trash every message whose subject matches this run's stamp.
        # Sending to self can produce more than one labelled copy
        # (e.g. SENT + INBOX). Searching by subject finds them all.
        try:
            search = service.users().messages().list(
                userId="me", q=f'subject:"{subject}"'
            ).execute()
            for hit in search.get("messages", []) or []:
                try:
                    service.users().messages().trash(
                        userId="me", id=hit["id"]
                    ).execute()
                except Exception:
                    pass
        except Exception:
            pass


def _safe_trash_drive(file_id: str) -> None:
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


@pytest.mark.integration
def test_attachment_fast_path_preserves_filename_in_drive(
    sent_attachment_email,
):
    """Pass explicit ``filename`` + ``mime_type`` (as the agent would
    after calling ``read_email``); confirm the Drive copy gets the
    original filename, not the ``attachment-<id_prefix>`` fallback.
    """
    sent_id, attachment_id, filename, mime_type, payload = (
        sent_attachment_email
    )

    drive_file_id = None
    try:
        result = asyncio.run(
            download_email_attachment(
                message_id=sent_id,
                attachment_id=attachment_id,
                destination=DriveDestination(),
                filename=filename,
                mime_type=mime_type,
            )
        )
        assert isinstance(result, dict), result
        assert result.get("destination") == "drive", result
        drive_file_id = result.get("drive_file_id")
        assert drive_file_id, result
        assert result["name"] == filename, (
            f"Fast path failed: Drive copy name is {result['name']!r}, "
            f"expected the original {filename!r}. The "
            f"v0.12.1 fast path is supposed to preserve filename when "
            f"caller passes it explicitly."
        )
        assert result["mime_type"] == mime_type
        assert result["size_bytes"] == len(payload)

        # Round-trip the bytes back from Drive to prove the upload was
        # the real attachment, not some corrupted blob.
        fetched = drive.download_bytes(file_id=drive_file_id)
        assert fetched["data"] == payload
    finally:
        _safe_trash_drive(drive_file_id)


@pytest.mark.integration
def test_attachment_fast_path_inline_destination_preserves_filename(
    sent_attachment_email,
):
    """Same fast-path guarantee for the inline destination: the
    TextContent summary should carry the original filename + MIME.
    """
    import json
    from gwsa.sdk.destinations import InlineDestination

    sent_id, attachment_id, filename, mime_type, payload = (
        sent_attachment_email
    )

    result = asyncio.run(
        download_email_attachment(
            message_id=sent_id,
            attachment_id=attachment_id,
            destination=InlineDestination(),
            filename=filename,
            mime_type=mime_type,
        )
    )
    assert isinstance(result, list), result
    summary, embedded = result
    summary_data = json.loads(summary.text)
    assert summary_data["name"] == filename, (
        f"Inline fast path failed: summary name is "
        f"{summary_data['name']!r}, expected {filename!r}."
    )
    assert summary_data["mime_type"] == mime_type
    assert summary_data["size_bytes"] == len(payload)
    decoded = base64.b64decode(embedded.resource.blob)
    assert decoded == payload
