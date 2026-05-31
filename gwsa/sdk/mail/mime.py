"""Faithful MIME reconstruction for reply and forward.

Reply and forward are **not** Gmail API primitives. Both are
client-side reconstructions assembled over ``drafts.create`` /
``messages.send`` — the caller hands Gmail a fully-formed raw MIME
message. The only natively reply-specific affordance Gmail offers is
**threading** (``threadId`` plus the ``In-Reply-To`` / ``References``
headers).

That means a faithful relay has to rebuild the message from the
source's full MIME. The decoded convenience view (``read_message``'s
``body.html`` / ``body.text`` plus a flat attachment list) is not
enough: it drops regular attachments and, critically, loses the
binding between an HTML ``<img src="cid:XXX">`` and the inline part
that carries ``Content-ID: <XXX>``. Re-attaching that part with a
freshly-generated Content-ID does not match the quoted HTML's ``cid:``
token, so the image renders broken.

The functions here fetch the source's raw MIME
(``messages.get?format=raw``), split it into body text/html plus
inline (``cid:``-referenced) and attachment parts, and reassemble a
new message that preserves every part's original Content-ID. Both
``forward_message`` and the inline-rebinding path of ``reply_message``
build on these helpers.
"""

from __future__ import annotations

import base64
import email
from email import policy
from email.message import EmailMessage, Message
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "fetch_raw_message",
    "split_parts",
    "assemble_message",
    "parse_message_structure",
]


def fetch_raw_message(service: Any, message_id: str) -> Message:
    """Fetch a message as raw RFC 2822 bytes and parse it.

    Uses ``messages.get?format=raw`` — the only format that exposes the
    full per-part MIME structure (Content-ID, Content-Disposition,
    nested multiparts) that ``format=full`` flattens away.

    Returns a parsed :class:`email.message.EmailMessage` (modern
    ``policy.default``), ready for :func:`split_parts`.
    """
    raw = service.users().messages().get(
        userId="me", id=message_id, format="raw"
    ).execute()
    data = base64.urlsafe_b64decode(raw["raw"])
    return email.message_from_bytes(data, policy=policy.default)


def split_parts(
    msg: Message,
) -> Tuple[Optional[str], Optional[str], List[Message], List[Message]]:
    """Split a parsed message into its reconstructable pieces.

    Walks every leaf part and classifies it:

    - the first non-attachment ``text/plain`` becomes the **text body**,
    - the first non-attachment ``text/html`` becomes the **html body**,
    - any leaf carrying a ``Content-ID`` or ``Content-Disposition:
      inline`` becomes an **inline part** (a ``cid:``-referenced
      resource such as a signature logo or embedded chart),
    - everything else with content becomes an **attachment part**.

    Returns ``(text_body, html_body, inline_parts, attachment_parts)``.
    The inline/attachment lists hold the original
    :class:`email.message.Message` leaves so callers can re-emit them
    with their Content-IDs intact via :func:`assemble_message`.
    """
    text_body: Optional[str] = None
    html_body: Optional[str] = None
    inline_parts: List[Message] = []
    attachment_parts: List[Message] = []

    for part in msg.walk():
        if part.is_multipart():
            continue

        ctype = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        content_id = part.get("Content-ID")
        filename = part.get_filename()

        is_body_candidate = (
            disposition != "attachment"
            and content_id is None
            and not filename
        )

        if ctype == "text/plain" and text_body is None and is_body_candidate:
            text_body = _decode_text(part)
            continue
        if ctype == "text/html" and html_body is None and is_body_candidate:
            html_body = _decode_text(part)
            continue

        if content_id is not None or disposition == "inline":
            inline_parts.append(part)
        else:
            attachment_parts.append(part)

    return text_body, html_body, inline_parts, attachment_parts


def assemble_message(
    *,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    subject: Optional[str] = None,
    text_body: str = "",
    html_body: Optional[str] = None,
    inline_parts: Optional[List[Message]] = None,
    attachment_parts: Optional[List[Message]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> EmailMessage:
    """Build a new MIME message, re-binding inline parts by Content-ID.

    Produces the same nested shape a native mail client emits for a
    forward with attachments::

        multipart/mixed
        ├── multipart/alternative
        │   ├── text/plain
        │   └── multipart/related
        │       ├── text/html
        │       └── <inline image, original Content-ID preserved>
        └── <attachment>

    Each inline part is re-attached with its **original** Content-ID, so
    the html body's existing ``cid:`` references still resolve. When
    there is no html body, inline parts are demoted to attachments
    (there is nothing for their ``cid:`` refs to bind to).
    """
    msg = EmailMessage(policy=policy.SMTP)
    if to:
        msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    if subject is not None:
        msg["Subject"] = subject
    for name, value in (headers or {}).items():
        if value:
            msg[name] = value

    msg.set_content(text_body or "")

    attachment_parts = list(attachment_parts or [])

    if html_body is not None:
        msg.add_alternative(html_body, subtype="html")
        for part in inline_parts or []:
            related = msg.get_payload()[1]
            _attach_related(related, part)
    elif inline_parts:
        # No html body to bind cid: refs to — carry them as attachments
        # so the bytes still travel, even though they won't render inline.
        attachment_parts = attachment_parts + list(inline_parts)

    for part in attachment_parts:
        _attach_attachment(msg, part)

    return msg


def parse_message_structure(msg: Message) -> Dict[str, Any]:
    """Expose the full per-part MIME structure of a parsed message.

    Unlike ``read_message`` (which returns a decoded body plus a flat
    attachment list), this surfaces, per non-body part: ``mime_type``,
    ``content_id``, ``disposition`` (inline vs attachment), ``filename``,
    ``size``, and ``cid_referenced`` — whether the html body actually
    points at this part via a ``cid:`` reference. This is the structure
    a faithful reconstruction needs.

    Returns a dict with ``body`` (text/html), ``parts`` (the list
    above), and ``inline_count`` / ``attachment_count`` tallies.
    """
    text_body, html_body, inline_parts, attachment_parts = split_parts(msg)
    html_lower = (html_body or "").lower()

    def describe(part: Message, disposition: str) -> Dict[str, Any]:
        content_id = part.get("Content-ID")
        stripped = content_id.strip("<>") if content_id else None
        cid_referenced = bool(
            stripped and f"cid:{stripped.lower()}" in html_lower
        )
        payload = part.get_payload(decode=True) or b""
        return {
            "mime_type": part.get_content_type(),
            "content_id": content_id,
            "disposition": disposition,
            "filename": part.get_filename(),
            "size": len(payload),
            "cid_referenced": cid_referenced,
        }

    parts = [describe(p, "inline") for p in inline_parts]
    parts += [describe(p, "attachment") for p in attachment_parts]

    return {
        "subject": msg.get("Subject"),
        "from": msg.get("From"),
        "to": msg.get("To"),
        "date": msg.get("Date"),
        "messageId": msg.get("Message-ID"),
        "body": {"text": text_body, "html": html_body},
        "parts": parts,
        "inline_count": len(inline_parts),
        "attachment_count": len(attachment_parts),
    }


# --- internal part helpers -------------------------------------------------


def _decode_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, AttributeError):
        return payload.decode("utf-8", errors="replace")


def _maintype_subtype(part: Message) -> Tuple[str, str]:
    maintype, _, subtype = part.get_content_type().partition("/")
    return maintype or "application", subtype or "octet-stream"


def _attach_related(container: EmailMessage, part: Message) -> None:
    """Attach an inline part, preserving its original Content-ID."""
    maintype, subtype = _maintype_subtype(part)
    content_id = part.get("Content-ID")
    filename = part.get_filename()
    kwargs: Dict[str, Any] = {}
    if content_id:
        kwargs["cid"] = content_id
    if filename:
        kwargs["filename"] = filename
    if maintype == "text":
        container.add_related(_decode_text(part), subtype=subtype, **kwargs)
    else:
        payload = part.get_payload(decode=True) or b""
        container.add_related(payload, maintype, subtype, **kwargs)


def _attach_attachment(msg: EmailMessage, part: Message) -> None:
    """Re-attach a regular attachment part byte-for-byte."""
    maintype, subtype = _maintype_subtype(part)
    filename = part.get_filename()
    kwargs: Dict[str, Any] = {}
    if filename:
        kwargs["filename"] = filename
    if maintype == "text":
        msg.add_attachment(_decode_text(part), subtype=subtype, **kwargs)
    else:
        payload = part.get_payload(decode=True) or b""
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, **kwargs)
