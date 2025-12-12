"""Gmail message read operations."""

import logging
import base64
from typing import Dict, Any, Optional

from .service import get_gmail_service

logger = logging.getLogger(__name__)


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
