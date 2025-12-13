"""Gmail message send operations."""

import logging
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List

from .service import get_gmail_service

logger = logging.getLogger(__name__)


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
