"""Offline tests for faithful forward / reply MIME reconstruction.

These exercise the real reconstruction code end-to-end with no network:
a small fixture message (one inline ``cid:`` image + one regular
attachment + html and text bodies) is fed through ``forward_message`` /
``reply_message`` via a fake Gmail service, and the bytes the SDK would
hand Gmail are decoded back and asserted against. The only seam is the
Gmail API object itself; every layer of MIME assembly runs unaltered.
"""

from __future__ import annotations

import base64
import email
from email import policy
from email.message import EmailMessage, Message
from unittest.mock import patch

from gwsa.sdk.mail.mime import (
    parse_message_structure,
    split_parts,
)
from gwsa.sdk.mail.send import forward_message, reply_message


# --- fixtures --------------------------------------------------------------

INLINE_PNG = b"\x89PNG\r\n\x1a\nFAKE-INLINE-IMAGE-BYTES"
PDF_BYTES = b"%PDF-1.4 fake report bytes \x00\x01\x02"


def _rich_source() -> EmailMessage:
    """A message with text + html bodies, one inline cid image, one pdf."""
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "Bob <bob@example.com>"
    msg["Subject"] = "Quarterly report"
    msg["Date"] = "Mon, 01 Jan 2026 10:00:00 +0000"
    msg["Message-ID"] = "<orig-123@example.com>"
    msg.set_content("Plain body text.")
    msg.add_alternative(
        '<html><body><p>HTML body</p>'
        '<img src="cid:logo123"></body></html>',
        subtype="html",
    )
    msg.get_payload()[1].add_related(
        INLINE_PNG, "image", "png", cid="<logo123>", filename="logo.png"
    )
    msg.add_attachment(
        PDF_BYTES, maintype="application", subtype="pdf", filename="report.pdf"
    )
    return msg


def _plain_source() -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "Bob <bob@example.com>"
    msg["Subject"] = "Just text"
    msg["Date"] = "Mon, 01 Jan 2026 10:00:00 +0000"
    msg["Message-ID"] = "<plain-1@example.com>"
    msg.set_content("Nothing but plain text here.")
    return msg


def _raw_of(msg: Message) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")


def _decode_sent(raw: str) -> Message:
    return email.message_from_bytes(
        base64.urlsafe_b64decode(raw), policy=policy.default
    )


# --- fake Gmail service ----------------------------------------------------


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Messages:
    def __init__(self, raw, sink):
        self._raw = raw
        self._sink = sink

    def get(self, userId, id, format):  # noqa: A002 - mirror API kwarg
        assert format == "raw"
        return _Exec({"raw": self._raw})

    def send(self, userId, body):
        self._sink.append(body["raw"])
        return _Exec({"id": "sent-1", "threadId": "thread-1"})


class _Drafts:
    def __init__(self, sink):
        self._sink = sink

    def create(self, userId, body):
        self._sink.append(body["message"]["raw"])
        return _Exec({"id": "draft-1", "message": {"id": "m-1"}})


class _Users:
    def __init__(self, raw, sink):
        self._raw = raw
        self._sink = sink

    def messages(self):
        return _Messages(self._raw, self._sink)

    def drafts(self):
        return _Drafts(self._sink)


class FakeGmailService:
    def __init__(self, raw):
        self._raw = raw
        self.sent: list[str] = []

    def users(self):
        return _Users(self._raw, self.sent)


# --- helpers ---------------------------------------------------------------


def _leaves(msg: Message):
    return [p for p in msg.walk() if not p.is_multipart()]


def _find(msg: Message, content_type: str) -> Message | None:
    for p in _leaves(msg):
        if p.get_content_type() == content_type:
            return p
    return None


# --- split_parts / structure ----------------------------------------------


def test_split_parts_categorizes_body_inline_and_attachment():
    text, html, inline, attach = split_parts(_rich_source())
    assert text.strip() == "Plain body text."
    assert "cid:logo123" in html
    assert [p.get("Content-ID") for p in inline] == ["<logo123>"]
    assert [p.get_filename() for p in attach] == ["report.pdf"]


def test_parse_message_structure_reports_cid_binding():
    structure = parse_message_structure(_rich_source())
    assert structure["inline_count"] == 1
    assert structure["attachment_count"] == 1

    inline = next(p for p in structure["parts"] if p["disposition"] == "inline")
    assert inline["content_id"] == "<logo123>"
    assert inline["mime_type"] == "image/png"
    assert inline["cid_referenced"] is True

    attachment = next(
        p for p in structure["parts"] if p["disposition"] == "attachment"
    )
    assert attachment["filename"] == "report.pdf"
    assert attachment["cid_referenced"] is False


# --- forward ---------------------------------------------------------------


def test_forward_preserves_attachments_inline_and_bodies():
    service = FakeGmailService(_raw_of(_rich_source()))
    with patch(
        "gwsa.sdk.mail.send.get_gmail_service", return_value=service
    ):
        result = forward_message(
            "orig-id", to="carol@example.com", note="Please review."
        )

    assert result["is_draft"] is False
    assert result["id"] == "sent-1"

    sent = _decode_sent(service.sent[0])
    assert sent["Subject"] == "Fwd: Quarterly report"
    assert sent["To"] == "carol@example.com"

    # (a) regular attachment survives byte-for-byte
    pdf = _find(sent, "application/pdf")
    assert pdf is not None
    assert pdf.get_payload(decode=True) == PDF_BYTES
    assert pdf.get_filename() == "report.pdf"

    # (b) inline image survives with its ORIGINAL Content-ID, so the
    #     quoted html's cid: reference still resolves
    png = _find(sent, "image/png")
    assert png is not None
    assert png.get_payload(decode=True) == INLINE_PNG
    assert png.get("Content-ID") == "<logo123>"

    # (c) both body alternatives present; html keeps the cid ref, the
    #     note and forwarded header are present
    html = _find(sent, "text/html")
    text = _find(sent, "text/plain")
    assert html is not None and 'cid:logo123' in html.get_content()
    assert "Please review." in text.get_content()
    assert "Forwarded message" in text.get_content()
    assert "Plain body text." in text.get_content()


def test_forward_plain_only_stays_plain_with_note():
    service = FakeGmailService(_raw_of(_plain_source()))
    with patch(
        "gwsa.sdk.mail.send.get_gmail_service", return_value=service
    ):
        forward_message("orig-id", to="carol@example.com", note="FYI")

    sent = _decode_sent(service.sent[0])
    assert sent["Subject"] == "Fwd: Just text"
    assert _find(sent, "text/html") is None
    text = _find(sent, "text/plain")
    assert "FYI" in text.get_content()
    assert "Nothing but plain text here." in text.get_content()


def test_forward_as_draft_uses_drafts_create():
    service = FakeGmailService(_raw_of(_rich_source()))
    with patch(
        "gwsa.sdk.mail.send.get_gmail_service", return_value=service
    ):
        result = forward_message(
            "orig-id", to="carol@example.com", as_draft=True
        )
    assert result["is_draft"] is True
    assert result["id"] == "draft-1"
    # the draft still carries the faithful rebuild
    sent = _decode_sent(service.sent[0])
    assert _find(sent, "application/pdf").get_payload(decode=True) == PDF_BYTES


# --- reply rebinding -------------------------------------------------------


def test_reply_rebinds_inline_cid_parts_in_quoted_html():
    service = FakeGmailService(_raw_of(_rich_source()))
    original_view = {
        "threadId": "thread-1",
        "messageId": "<orig-123@example.com>",
        "subject": "Quarterly report",
        "from": "Alice <alice@example.com>",
        "date": "Mon, 01 Jan 2026 10:00:00 +0000",
        "body": {
            "text": "Plain body text.",
            "html": '<p>HTML body</p><img src="cid:logo123">',
        },
    }
    with patch(
        "gwsa.sdk.mail.send.get_gmail_service", return_value=service
    ), patch(
        "gwsa.sdk.mail.send.read_message", return_value=original_view
    ):
        reply_message("orig-id", body="Thanks, looks good.")

    sent = _decode_sent(service.sent[0])

    # quoted html still references the inline image...
    html = _find(sent, "text/html")
    assert html is not None and "cid:logo123" in html.get_content()

    # ...and the matching inline part is re-attached with its Content-ID
    png = _find(sent, "image/png")
    assert png is not None
    assert png.get("Content-ID") == "<logo123>"
    assert png.get_payload(decode=True) == INLINE_PNG

    # a reply does NOT re-carry the original's file attachments
    assert _find(sent, "application/pdf") is None

    # threading headers are set
    assert sent["In-Reply-To"] == "<orig-123@example.com>"
    assert sent["Subject"] == "Re: Quarterly report"
