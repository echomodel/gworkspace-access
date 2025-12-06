import logging
import json
import base64
from typing import List, Dict, Any, Optional, Tuple
from ..mail import _get_gmail_service # Changed to relative import

logger = logging.getLogger(__name__)

from ..decorators import require_scopes

@require_scopes('mail')
def search_messages(query_string: str, page_token: Optional[str] = None, max_results: int = 25, format: str = 'full') -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Searches for Gmail messages matching the given query string with pagination support.

    Args:
        query_string: Gmail API query string
        page_token: Token for pagination (None for first page)
        max_results: Maximum number of messages to return (default 25, max 500).
                     Note: 'full' format with body extraction can be slow, consider lower max_results.
        format: 'full' (includes body, labelIds, snippet) or 'metadata' (headers only, fast)

    Returns:
        Tuple of (list of message dicts, metadata dict with pagination info)
        'full' format includes: id, subject, sender, date, labelIds, body, snippet
        'metadata' format includes: id, subject, sender, date, labelIds
        Metadata dict contains: resultSizeEstimate, nextPageToken (if more pages available)
    """
    try:
        service = _get_gmail_service()
        logger.debug("Gmail API service built successfully.")
        logger.debug(f"Searching for emails with query: '{query_string}' (pageToken={page_token}, maxResults={max_results}, format={format})")

        # Build the list request with pagination
        list_kwargs = {"userId": "me", "q": query_string, "maxResults": max_results}
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
        else:
            logger.debug(f"Found {len(messages)} messages on this page (total estimate: {result_size_estimate})")
            parsed_messages = []
            for message in messages:
                # Get message details (format determines what we retrieve)
                msg = service.users().messages().get(userId='me', id=message['id'], format=format).execute()
                headers = msg['payload'].get('headers', [])
                label_ids = msg.get('labelIds', [])

                subject = "N/A"
                from_addr = "N/A"
                to_addr = "N/A"
                date = "N/A"

                for header in headers:
                    if header['name'] == 'Subject':
                        subject = header['value']
                    elif header['name'] == 'From':
                        from_addr = header['value']
                    elif header['name'] == 'To':
                        to_addr = header['value']
                    elif header['name'] == 'Date':
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
                    body = ""
                    if 'parts' in msg['payload']:
                        # Multipart message - find text/plain part
                        for part in msg['payload']['parts']:
                            if part['mimeType'] == 'text/plain':
                                if 'data' in part['body']:
                                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                                    break
                    else:
                        # Single part message
                        if 'body' in msg['payload'] and 'data' in msg['payload']['body']:
                            body = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8', errors='ignore')

                    # Use snippet as fallback
                    snippet = msg.get('snippet', '')

                    msg_dict['body'] = body
                    msg_dict['snippet'] = snippet

                parsed_messages.append(msg_dict)
                logger.debug(f"- Subject: {subject}, From: {from_addr}, To: {to_addr}, Date: {date}, Labels: {label_ids}")

            logger.debug(f"Successfully parsed {len(parsed_messages)} messages")
            return parsed_messages, metadata

    except Exception as e: # Catch all exceptions, including HttpError from _get_gmail_service
        logger.critical(f"An unexpected error occurred during message search: {e}", exc_info=True)
        raise