"""Gmail message send operations."""

import logging
import base64
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List, Tuple

from .service import get_gmail_service
from .read import read_message
from .mime import assemble_message, fetch_raw_message, split_parts

logger = logging.getLogger(__name__)


def _format_quoted_reply(
    original: Dict[str, Any],
    new_body: str,
    new_html_body: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Format a reply with quoted original content.

    Args:
        original: The original message dict from read_message()
        new_body: The new reply text (plain text)
        new_html_body: Optional custom HTML body of the reply.

    Returns:
        Tuple of (plain_text_body, html_body)
    """
    sender = original.get("from", "Unknown")
    date = original.get("date", "Unknown date")
    original_text = original.get("body", {}).get("text") or ""
    original_html = original.get("body", {}).get("html")

    # Plain text version: prefix each line with >
    quoted_lines = "\n".join(f"> {line}" for line in original_text.split("\n"))
    plain = f"{new_body}\n\nOn {date}, {sender} wrote:\n{quoted_lines}"

    # HTML version
    if new_html_body is not None:
        new_body_html = new_html_body
    else:
        new_body_html = html.escape(new_body).replace("\n", "<br>")

    if original_html:
        quoted_content = original_html
    else:
        # Convert plain text to HTML
        quoted_content = html.escape(original_text).replace("\n", "<br>")

    html_body = f"""{new_body_html}
<br><br>
<div class="gmail_quote">
<div>On {html.escape(date)}, {html.escape(sender)} wrote:</div>
<blockquote style="margin:0 0 0 .8ex;border-left:1px #ccc solid;padding-left:1ex">
{quoted_content}
</blockquote>
</div>"""

    return plain, html_body


def send_message(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send an email message via Gmail.

    Args:
        to: Recipient email address (comma-separated for multiple)
        subject: Email subject line
        body: Plain text body of the email
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)
        html_body: Optional HTML body (if provided, sends multipart)
        account: Optional account selector — name or email. Omit to
            send as the user's default account.

    Returns:
        Dict containing:
            - id: Message ID of the sent email
            - threadId: Thread ID
            - labelIds: Labels applied to the sent message
    """
    service = get_gmail_service(account=account)
    logger.debug(f"Sending email to: {to}, subject: {subject}")

    # Build the message
    if html_body:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body, "plain"))
        message.attach(MIMEText(html_body, "html"))
    else:
        message = MIMEText(body, "plain")

    message["to"] = to
    message["subject"] = subject

    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    # Encode the message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    # Send the message
    result = service.users().messages().send(
        userId="me",
        body={"raw": encoded_message}
    ).execute()

    logger.info(f"Email sent successfully. Message ID: {result.get('id')}")

    return {
        "id": result.get("id"),
        "threadId": result.get("threadId"),
        "labelIds": result.get("labelIds", []),
    }


def create_draft(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a draft email in Gmail.

    Args:
        to: Recipient email address (comma-separated for multiple)
        subject: Email subject line
        body: Plain text body of the email
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)
        html_body: Optional HTML body (if provided, sends multipart)
        account: Optional account selector — name or email. Omit to
            create the draft in the user's default account.

    Returns:
        Dict containing draft info including id and message details.
    """
    service = get_gmail_service(account=account)
    logger.debug(f"Creating draft to: {to}, subject: {subject}")

    # Build the message
    if html_body:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body, "plain"))
        message.attach(MIMEText(html_body, "html"))
    else:
        message = MIMEText(body, "plain")

    message["to"] = to
    message["subject"] = subject

    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    # Encode the message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    # Create the draft
    result = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": encoded_message}}
    ).execute()

    logger.info(f"Draft created successfully. Draft ID: {result.get('id')}")

    return {
        "id": result.get("id"),
        "message": result.get("message", {}),
    }


def reply_message(
    reply_to_message_id: str,
    body: str,
    include_quote: bool = True,
    as_draft: bool = False,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reply to an existing email message.

    Creates a properly threaded reply with quoted original content.

    Args:
        reply_to_message_id: The message ID to reply to
        body: Plain text body of the reply
        include_quote: Whether to include quoted original (default True)
        as_draft: If True, create a draft instead of sending (default False)
        html_body: Optional HTML body of the reply. If include_quote is True,
            this HTML content is prepended above the quoted original.
        account: Optional account selector — name or email. Omit to
            reply as the user's default account.

    Returns:
        Dict containing:
            - id: Message/draft ID
            - threadId: Thread ID
            - If draft: includes draft info
    """
    service = get_gmail_service(account=account)

    original = read_message(reply_to_message_id, account=account)
    thread_id = original.get("threadId")
    message_id = original.get("messageId")  # RFC 2822 Message-ID header
    original_subject = original.get("subject", "")
    reply_to_addr = original.get("from")

    logger.debug(f"Replying to message {reply_to_message_id} in thread {thread_id}")

    # Build subject with Re: prefix if needed
    if original_subject.lower().startswith("re:"):
        subject = original_subject
    else:
        subject = f"Re: {original_subject}"

    # Build body with or without quoted content
    if include_quote:
        plain_body, html_body = _format_quoted_reply(original, body, html_body)
    else:
        plain_body = body
        html_body = None

    # Threading headers (RFC 2822)
    headers = {}
    if message_id:
        headers["In-Reply-To"] = message_id
        headers["References"] = message_id

    # When the quoted html carries inline cid: images (signature logos,
    # embedded charts), re-attach the matching Content-ID parts so the
    # quoted tail still renders. A reply does NOT re-carry the original's
    # file attachments — only the inline parts the quoted html points at.
    inline_parts = []
    if html_body and original.get("body", {}).get("html"):
        raw = fetch_raw_message(service, reply_to_message_id)
        _, _, inline_parts, _ = split_parts(raw)

    message = assemble_message(
        to=reply_to_addr,
        subject=subject,
        text_body=plain_body,
        html_body=html_body,
        inline_parts=inline_parts,
        headers=headers,
    )

    # Encode the message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    # Send or create draft
    if as_draft:
        result = service.users().drafts().create(
            userId="me",
            body={
                "message": {
                    "raw": encoded_message,
                    "threadId": thread_id,
                }
            }
        ).execute()

        logger.info(f"Reply draft created. Draft ID: {result.get('id')}")
        return {
            "id": result.get("id"),
            "threadId": thread_id,
            "message": result.get("message", {}),
            "is_draft": True,
        }
    else:
        result = service.users().messages().send(
            userId="me",
            body={
                "raw": encoded_message,
                "threadId": thread_id,
            }
        ).execute()

        logger.info(f"Reply sent. Message ID: {result.get('id')}")
        return {
            "id": result.get("id"),
            "threadId": result.get("threadId"),
            "labelIds": result.get("labelIds", []),
            "is_draft": False,
        }


def _format_forwarded_body(
    original: Any,
    note: Optional[str],
    html_note: Optional[str],
    text_body: Optional[str],
    html_body: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Build the forwarded body, prepending the caller's note.

    Returns ``(plain_text, html_or_None)``. The html alternative is
    produced only when the source had an html body or the caller passed
    an ``html_note`` — a plain-only source forwarded with a plain note
    stays plain, matching what a native client does.
    """
    header_lines = [
        "---------- Forwarded message ----------",
        f"From: {original.get('From', '') or ''}",
        f"Date: {original.get('Date', '') or ''}",
        f"Subject: {original.get('Subject', '') or ''}",
        f"To: {original.get('To', '') or ''}",
    ]
    header_text = "\n".join(header_lines)

    note_text = f"{note}\n\n" if note else ""
    plain = f"{note_text}{header_text}\n\n{text_body or ''}"

    produce_html = html_body is not None or html_note is not None
    if not produce_html:
        return plain, None

    header_html = "<br>".join(html.escape(line) for line in header_lines)
    if html_note:
        note_html_block = f"{html_note}<br><br>"
    elif note:
        note_html_block = f"{html.escape(note).replace(chr(10), '<br>')}<br><br>"
    else:
        note_html_block = ""

    if html_body is not None:
        quoted_html = html_body
    elif text_body:
        quoted_html = html.escape(text_body).replace("\n", "<br>")
    else:
        quoted_html = ""

    new_html = (
        f"{note_html_block}"
        f'<div class="gmail_forward">{header_html}<br><br>{quoted_html}</div>'
    )
    return plain, new_html


def forward_message(
    message_id: str,
    to: str,
    note: Optional[str] = None,
    html_note: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    as_draft: bool = False,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """Forward a Gmail message, preserving its full MIME fidelity.

    Forward is not a Gmail API primitive — it is reconstructed from the
    source's raw MIME (``messages.get?format=raw``). This rebuild
    preserves:

    - every regular attachment, byte-for-byte,
    - every inline part **with its original Content-ID**, so the quoted
      html's ``cid:`` references still resolve (signature logos,
      embedded charts),
    - both the html and plain-text body alternatives,

    then prepends the caller's ``note`` / ``html_note``. A forward
    starts a new thread (no ``threadId`` / reply headers), mirroring a
    native mail client.

    Args:
        message_id: Gmail message ID to forward.
        to: Recipient(s), comma-separated.
        note: Optional plain-text note prepended above the forwarded
            content.
        html_note: Optional html note. When the source has an html body
            this is used as the html lead-in; otherwise ``note`` is
            html-escaped.
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).
        as_draft: Create a draft instead of sending (default False).
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with ``id``, ``threadId`` (or draft ``message`` block),
        ``labelIds``, and ``is_draft``.
    """
    service = get_gmail_service(account=account)
    logger.debug(f"Forwarding message {message_id} to: {to}")

    original = fetch_raw_message(service, message_id)
    text_body, html_body, inline_parts, attachment_parts = split_parts(original)

    orig_subject = original.get("Subject", "") or ""
    lowered = orig_subject.lower()
    if lowered.startswith("fwd:") or lowered.startswith("fw:"):
        subject = orig_subject
    else:
        subject = f"Fwd: {orig_subject}"

    plain_body, new_html = _format_forwarded_body(
        original, note, html_note, text_body, html_body
    )

    message = assemble_message(
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        text_body=plain_body,
        html_body=new_html,
        inline_parts=inline_parts,
        attachment_parts=attachment_parts,
    )

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    if as_draft:
        result = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": encoded_message}},
        ).execute()
        logger.info(f"Forward draft created. Draft ID: {result.get('id')}")
        return {
            "id": result.get("id"),
            "message": result.get("message", {}),
            "is_draft": True,
        }

    result = service.users().messages().send(
        userId="me",
        body={"raw": encoded_message},
    ).execute()
    logger.info(f"Forward sent. Message ID: {result.get('id')}")
    return {
        "id": result.get("id"),
        "threadId": result.get("threadId"),
        "labelIds": result.get("labelIds", []),
        "is_draft": False,
    }
