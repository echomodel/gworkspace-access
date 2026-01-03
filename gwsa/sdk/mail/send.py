"""Gmail message send operations."""

import logging
import base64
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List, Tuple

from .service import get_gmail_service
from .read import read_message

logger = logging.getLogger(__name__)


def _format_quoted_reply(original: Dict[str, Any], new_body: str) -> Tuple[str, str]:
    """
    Format a reply with quoted original content.

    Args:
        original: The original message dict from read_message()
        new_body: The new reply text (plain text)

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
    profile: str = None,
    use_adc: bool = False,
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
        profile: Optional profile name to use
        use_adc: Force use of Application Default Credentials

    Returns:
        Dict containing:
            - id: Message ID of the sent email
            - threadId: Thread ID
            - labelIds: Labels applied to the sent message

    Raises:
        Exception: If sending fails
    """
    service = get_gmail_service(profile=profile, use_adc=use_adc)
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
    profile: str = None,
    use_adc: bool = False,
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
        profile: Optional profile name to use
        use_adc: Force use of Application Default Credentials

    Returns:
        Dict containing draft info including id and message details

    Raises:
        Exception: If draft creation fails
    """
    service = get_gmail_service(profile=profile, use_adc=use_adc)
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
    profile: str = None,
    use_adc: bool = False,
) -> Dict[str, Any]:
    """
    Reply to an existing email message.

    Creates a properly threaded reply with quoted original content.

    Args:
        reply_to_message_id: The message ID to reply to
        body: Plain text body of the reply
        include_quote: Whether to include quoted original (default True)
        as_draft: If True, create a draft instead of sending (default False)
        profile: Optional profile name to use
        use_adc: Force use of Application Default Credentials

    Returns:
        Dict containing:
            - id: Message/draft ID
            - threadId: Thread ID
            - If draft: includes draft info

    Raises:
        Exception: If reply fails
    """
    service = get_gmail_service(profile=profile, use_adc=use_adc)

    # Fetch original message to get threading info
    original = read_message(reply_to_message_id, profile=profile, use_adc=use_adc)
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
        plain_body, html_body = _format_quoted_reply(original, body)
    else:
        plain_body = body
        html_body = None

    # Build the MIME message
    if html_body:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(plain_body, "plain"))
        message.attach(MIMEText(html_body, "html"))
    else:
        message = MIMEText(plain_body, "plain")

    message["to"] = reply_to_addr
    message["subject"] = subject

    # Threading headers (RFC 2822)
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = message_id

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
