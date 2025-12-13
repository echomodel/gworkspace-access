"""Gmail message read operations."""

import logging
import base64
from typing import Dict, Any, Optional, List

from .service import get_gmail_service

logger = logging.getLogger(__name__)


def _extract_attachments(payload: dict) -> List[Dict[str, Any]]:
    """
    Extract attachment metadata from a message payload.

    Recursively searches through MIME parts to find attachments.
    An attachment is identified by having a filename and attachmentId.

    Args:
        payload: The message payload from Gmail API

    Returns:
        List of attachment metadata dicts, each containing:
            - attachmentId: ID needed to download the attachment
            - filename: Original filename
            - mimeType: MIME type (e.g., "application/pdf")
            - size: Size in bytes
    """
    attachments = []

    def process_part(part: dict):
        """Process a single part, looking for attachments."""
        filename = part.get('filename', '')
        body = part.get('body', {})
        attachment_id = body.get('attachmentId')

        # An attachment has both a filename and an attachmentId
        if filename and attachment_id:
            attachments.append({
                'attachmentId': attachment_id,
                'filename': filename,
                'mimeType': part.get('mimeType', 'application/octet-stream'),
                'size': body.get('size', 0),
            })

        # Recurse into nested parts
        if 'parts' in part:
            for subpart in part['parts']:
                process_part(subpart)

    # Process all parts
    if 'parts' in payload:
        for part in payload['parts']:
            process_part(part)

    return attachments


def read_message(
    message_id: str,
    profile: str = None,
    use_adc: bool = False,
) -> Dict[str, Any]:
    """
    Retrieve the full content of a specific Gmail message.

    Args:
        message_id: The Gmail message ID
        profile: Optional profile name to use
        use_adc: Force use of Application Default Credentials

    Returns:
        Dict containing message details:
            - id: Message ID
            - subject: Email subject
            - from: Sender address
            - to: Recipient address
            - date: Date header
            - snippet: Short preview
            - body: Dict with 'text' and 'html' content
            - labelIds: List of label IDs
            - attachments: List of attachment metadata (filename, mimeType, size, attachmentId)
    """
    service = get_gmail_service(profile=profile, use_adc=use_adc)
    logger.debug(f"Retrieving message with ID: {message_id}")

    msg = service.users().messages().get(
        userId='me', id=message_id, format='full'
    ).execute()

    headers = msg['payload']['headers']
    subject = _get_header(headers, 'Subject')
    from_addr = _get_header(headers, 'From')
    to_addr = _get_header(headers, 'To')
    date = _get_header(headers, 'Date')

    # Extract both text and html body parts
    text_body, html_body = _extract_body_parts(msg['payload'])

    # Extract attachment metadata
    attachments = _extract_attachments(msg['payload'])

    message_details = {
        "id": message_id,
        "subject": subject,
        "from": from_addr,
        "to": to_addr,
        "date": date,
        "snippet": msg.get('snippet', ''),
        "body": {
            "text": text_body,
            "html": html_body
        },
        "labelIds": msg.get('labelIds', []),
        "attachments": attachments,
    }

    logger.debug(f"Successfully retrieved message: '{subject}'")
    return message_details


def _get_header(headers: list, name: str, default: str = 'N/A') -> str:
    """Get a header value by name."""
    for header in headers:
        if header['name'].lower() == name.lower():
            return header['value']
    return default


def _extract_body_parts(payload: dict) -> tuple:
    """
    Extract text and HTML body parts from a message payload.

    Returns:
        Tuple of (text_body, html_body)
    """
    text_body = None
    html_body = None

    def extract_from_part(part: dict) -> Optional[str]:
        """Extract and decode body content from a MIME part."""
        if 'body' in part and 'data' in part['body']:
            encoded_data = part['body']['data']
            return base64.urlsafe_b64decode(encoded_data).decode('utf-8', errors='ignore')
        return None

    def process_part(part: dict):
        """Process a single part, looking for text/plain and text/html."""
        nonlocal text_body, html_body

        mime_type = part.get('mimeType', '')

        if mime_type == 'text/plain' and text_body is None:
            text_body = extract_from_part(part)
        elif mime_type == 'text/html' and html_body is None:
            html_body = extract_from_part(part)

        # Also check nested parts
        if 'parts' in part:
            for subpart in part['parts']:
                process_part(subpart)

    # Check for multipart message
    if 'parts' in payload:
        for part in payload['parts']:
            process_part(part)
    else:
        # Simple message, check top-level body
        text_body = extract_from_part(payload)

    return text_body, html_body


def get_attachment(
    message_id: str,
    attachment_id: str,
    profile: str = None,
    use_adc: bool = False,
) -> Dict[str, Any]:
    """
    Download an attachment from a Gmail message.

    Args:
        message_id: The Gmail message ID containing the attachment
        attachment_id: The attachment ID (from read_message attachments list)
        profile: Optional profile name to use
        use_adc: Force use of Application Default Credentials

    Returns:
        Dict containing:
            - data: Base64-decoded binary content of the attachment
            - size: Size in bytes
    """
    service = get_gmail_service(profile=profile, use_adc=use_adc)
    logger.debug(f"Downloading attachment {attachment_id} from message {message_id}")

    attachment = service.users().messages().attachments().get(
        userId='me',
        messageId=message_id,
        id=attachment_id
    ).execute()

    # Decode the base64url-encoded data
    data = base64.urlsafe_b64decode(attachment['data'])

    logger.debug(f"Downloaded attachment: {len(data)} bytes")
    return {
        'data': data,
        'size': attachment.get('size', len(data)),
    }
