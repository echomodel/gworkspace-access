"""Gmail message send operations."""

import logging
import base64
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, getaddresses
from typing import Dict, Any, Optional, List, Tuple

from .service import get_gmail_service
from .read import read_message
from .mime import assemble_message, fetch_raw_message, split_parts

logger = logging.getLogger(__name__)


def _get_active_account_email(account: Optional[str] = None) -> Optional[str]:
    """Return the active GoogleAccount email from context if available."""
    try:
        from ..auth import get_google_account_creds

        _, chosen = get_google_account_creds(account=account)
        return chosen.email if chosen else None
    except Exception:
        return None


def _parse_addrs(header_val: Optional[str]) -> List[Tuple[str, str]]:
    """Parse an RFC 2822 address header into (display_name, email) pairs."""
    if not header_val or header_val == "N/A":
        return []
    return [(name, addr) for name, addr in getaddresses([header_val]) if addr]


def _resolve_reply_recipients(
    original: Dict[str, Any],
    self_email: Optional[str],
    reply_all: bool = True,
    to: Optional[str] = None,
    cc: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Resolve (to, cc) headers for a reply or follow-up message."""
    self_norm = self_email.strip().lower() if self_email else None
    from_addrs = _parse_addrs(original.get("from"))
    reply_to_addrs = _parse_addrs(original.get("replyTo"))
    orig_to_addrs = _parse_addrs(original.get("to"))
    orig_cc_addrs = _parse_addrs(original.get("cc"))

    is_self_sent = bool(
        self_norm
        and from_addrs
        and all(addr.lower() == self_norm for _, addr in from_addrs)
    )

    if to is not None:
        resolved_to = to
        to_seen = {addr.lower() for _, addr in _parse_addrs(to)}
    else:
        to_pairs: List[Tuple[str, str]] = []
        to_seen = set()

        if is_self_sent:
            candidates = orig_to_addrs if reply_all else orig_to_addrs[:1]
            for name, addr in candidates:
                key = addr.lower()
                if key != self_norm and key not in to_seen:
                    to_seen.add(key)
                    to_pairs.append((name, addr))
        else:
            primary = reply_to_addrs or from_addrs
            for name, addr in primary:
                key = addr.lower()
                if key not in to_seen:
                    to_seen.add(key)
                    to_pairs.append((name, addr))
            if reply_all:
                for name, addr in orig_to_addrs:
                    key = addr.lower()
                    if key != self_norm and key not in to_seen:
                        to_seen.add(key)
                        to_pairs.append((name, addr))

        if not to_pairs:
            fallback = orig_to_addrs if is_self_sent else (reply_to_addrs or from_addrs)
            for name, addr in fallback:
                key = addr.lower()
                if key not in to_seen:
                    to_seen.add(key)
                    to_pairs.append((name, addr))

        resolved_to = (
            ", ".join(formataddr(pair) for pair in to_pairs)
            if to_pairs
            else (original.get("from") or "")
        )

    if cc is not None:
        resolved_cc = cc or None
    elif reply_all:
        cc_pairs: List[Tuple[str, str]] = []
        cc_seen = set(to_seen)
        if self_norm:
            cc_seen.add(self_norm)
        for name, addr in orig_cc_addrs:
            key = addr.lower()
            if key not in cc_seen:
                cc_seen.add(key)
                cc_pairs.append((name, addr))
        resolved_cc = (
            ", ".join(formataddr(pair) for pair in cc_pairs) if cc_pairs else None
        )
    else:
        resolved_cc = None

    return resolved_to, resolved_cc


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
    body: Optional[str] = None,
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
        body: Optional plain text body of the email
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)
        html_body: Optional HTML body (if provided, sends HTML or multipart)
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
    if html_body and body is not None:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body, "plain"))
        message.attach(MIMEText(html_body, "html"))
    elif html_body:
        message = MIMEText(html_body, "html")
    else:
        message = MIMEText(body or "", "plain")

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
    body: Optional[str] = None,
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
        body: Optional plain text body of the email
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)
        html_body: Optional HTML body (if provided, sends HTML or multipart)
        account: Optional account selector — name or email. Omit to
            create the draft in the user's default account.

    Returns:
        Dict containing draft info including id and message details.
    """
    service = get_gmail_service(account=account)
    logger.debug(f"Creating draft to: {to}, subject: {subject}")

    # Build the message
    if html_body and body is not None:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body, "plain"))
        message.attach(MIMEText(html_body, "html"))
    elif html_body:
        message = MIMEText(html_body, "html")
    else:
        message = MIMEText(body or "", "plain")

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
    body: Optional[str] = None,
    include_quote: bool = True,
    as_draft: bool = False,
    html_body: Optional[str] = None,
    reply_all: bool = True,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reply to an existing email message.

    Creates a properly threaded reply with quoted original content and
    full recipient preservation.

    Args:
        reply_to_message_id: The message ID to reply to
        body: Optional plain text body of the reply
        include_quote: Whether to include quoted original (default True)
        as_draft: If True, create a draft instead of sending (default False)
        html_body: Optional HTML body of the reply. If include_quote is True,
            this HTML content is prepended above the quoted original.
        reply_all: If True (default), include all other original To and Cc
            recipients (excluding the active user's own email address). If
            False, reply only to the sender.
        to: Optional explicit To override (comma-separated).
        cc: Optional explicit Cc override (comma-separated).
        bcc: Optional BCC recipients (comma-separated).
        account: Optional account selector — name or email. Omit to
            reply as the user's default account.

    Returns:
        Dict containing:
            - id: Message/draft ID
            - threadId: Thread ID
            - to: Resolved To header
            - cc: Resolved Cc header (or None)
            - subject: Reply subject line
            - If draft: includes draft info
    """
    service = get_gmail_service(account=account)

    original = read_message(reply_to_message_id, account=account)
    thread_id = original.get("threadId")
    message_id = original.get("messageId")  # RFC 2822 Message-ID header
    if message_id == "N/A":
        message_id = None
    orig_references = original.get("references")
    if orig_references == "N/A":
        orig_references = None
    original_subject = original.get("subject", "")

    self_email = _get_active_account_email(account=account)
    resolved_to, resolved_cc = _resolve_reply_recipients(
        original=original,
        self_email=self_email,
        reply_all=reply_all,
        to=to,
        cc=cc,
    )

    logger.debug(f"Replying to message {reply_to_message_id} in thread {thread_id}")

    # Build subject with Re: prefix if needed
    if original_subject.lower().startswith("re:"):
        subject = original_subject
    else:
        subject = f"Re: {original_subject}"

    # Build body with or without quoted content
    effective_body = body or ""
    if include_quote:
        plain_body, html_body = _format_quoted_reply(
            original, effective_body, html_body
        )
    else:
        plain_body = effective_body

    # Threading headers (RFC 2822)
    headers = {}
    if message_id:
        headers["In-Reply-To"] = message_id
        if orig_references:
            headers["References"] = (
                f"{orig_references} {message_id}"
                if message_id not in orig_references
                else orig_references
            )
        else:
            headers["References"] = message_id
    elif orig_references:
        headers["References"] = orig_references

    # When the quoted html carries inline cid: images (signature logos,
    # embedded charts), re-attach the matching Content-ID parts so the
    # quoted tail still renders. A reply does NOT re-carry the original's
    # file attachments — only the inline parts the quoted html points at.
    inline_parts = []
    if include_quote and html_body and original.get("body", {}).get("html"):
        raw = fetch_raw_message(service, reply_to_message_id)
        _, _, inline_parts, _ = split_parts(raw)

    message = assemble_message(
        to=resolved_to,
        cc=resolved_cc,
        bcc=bcc,
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
            "to": resolved_to,
            "cc": resolved_cc,
            "subject": subject,
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
            "to": resolved_to,
            "cc": resolved_cc,
            "subject": subject,
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
