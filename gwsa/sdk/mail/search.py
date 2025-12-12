"""Gmail message search operations."""

import logging
import base64
from typing import List, Dict, Any, Optional, Tuple

from .service import get_gmail_service

logger = logging.getLogger(__name__)


def search_messages(
    query: str,
    page_token: Optional[str] = None,
    max_results: int = 25,
    format: str = 'full',
    profile: str = None,
    use_adc: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Search for Gmail messages matching the given query.

    Args:
        query: Gmail API query string (e.g., "from:someone@example.com")
        page_token: Token for pagination (None for first page)
        max_results: Maximum number of messages to return (default 25, max 500)
        format: 'full' (includes body) or 'metadata' (headers only, faster)
        profile: Optional profile name to use
        use_adc: Force use of Application Default Credentials

    Returns:
        Tuple of (list of message dicts, metadata dict with pagination info)
        'full' format includes: id, subject, from, to, date, labelIds, body, snippet
        'metadata' format includes: id, subject, from, to, date, labelIds
        Metadata dict contains: resultSizeEstimate, nextPageToken
    """
    service = get_gmail_service(profile=profile, use_adc=use_adc)
    logger.debug(f"Searching for emails with query: '{query}'")

    # Build the list request with pagination
    list_kwargs = {"userId": "me", "q": query, "maxResults": max_results}
    if page_token:
        list_kwargs["pageToken"] = page_token

    results = service.users().messages().list(**list_kwargs).execute()
    messages = results.get("messages", [])
    result_size_estimate = results.get("resultSizeEstimate", 0)
    next_page_token = results.get("nextPageToken", None)

    metadata = {
        "resultSizeEstimate": result_size_estimate,
        "nextPageToken": next_page_token
    }

    if not messages:
        logger.debug("No messages found matching the criteria.")
        return [], metadata

    logger.debug(f"Found {len(messages)} messages on this page")

    parsed_messages = []
    for message in messages:
        msg = service.users().messages().get(
            userId='me', id=message['id'], format=format
        ).execute()

        headers = msg['payload'].get('headers', [])
        label_ids = msg.get('labelIds', [])

        subject = "N/A"
        from_addr = "N/A"
        to_addr = "N/A"
        date = "N/A"

        for header in headers:
            name = header['name'].lower()
            if name == 'subject':
                subject = header['value']
            elif name == 'from':
                from_addr = header['value']
            elif name == 'to':
                to_addr = header['value']
            elif name == 'date':
                date = header['value']

        msg_dict = {
            "id": message['id'],
            "subject": subject,
            "from": from_addr,
            "to": to_addr,
            "date": date,
            "labelIds": label_ids
        }

        # Extract body and snippet only if format='full'
        if format == 'full':
            body = _extract_body(msg)
            snippet = msg.get('snippet', '')
            msg_dict['body'] = body
            msg_dict['snippet'] = snippet

        parsed_messages.append(msg_dict)

    logger.debug(f"Successfully parsed {len(parsed_messages)} messages")
    return parsed_messages, metadata


def _extract_body(msg: dict) -> str:
    """Extract plain text body from a message."""
    body = ""

    if 'parts' in msg['payload']:
        # Multipart message - find text/plain part
        for part in msg['payload']['parts']:
            if part['mimeType'] == 'text/plain':
                if 'data' in part['body']:
                    body = base64.urlsafe_b64decode(
                        part['body']['data']
                    ).decode('utf-8', errors='ignore')
                    break
    else:
        # Single part message
        if 'body' in msg['payload'] and 'data' in msg['payload']['body']:
            body = base64.urlsafe_b64decode(
                msg['payload']['body']['data']
            ).decode('utf-8', errors='ignore')

    return body
