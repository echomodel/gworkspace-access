"""Google Chat service factory for GWSA SDK."""

import logging
from typing import Any

from googleapiclient.discovery import build

from ..auth import get_credentials
from ..timing import time_api_call

logger = logging.getLogger(__name__)


def get_chat_service(profile: str = None, use_adc: bool = False) -> Any:
    """
    Get an authenticated Google Chat API service object.

    Args:
        profile: Optional profile name to use (defaults to active profile)
        use_adc: Force use of Application Default Credentials

    Returns:
        Google Chat API service object

    Raises:
        ValueError: If no profile configured
        Exception: If authentication fails
    """
    creds, source = get_credentials(profile=profile, use_adc=use_adc)
    logger.debug(f"Building Chat service using credentials from: {source}")
    return build("chat", "v1", credentials=creds)

@time_api_call
def list_messages(space_id: str, filter: str = None, page_size: int = 25, page_token: str = None) -> dict:
    """
    Lists messages in a Google Chat space, with optional filtering.

    NOTE: The filter only supports filtering by 'createTime' and 'thread.name'.
    It does NOT support full-text search.

    Args:
        space_id: The resource name of the space (e.g., "spaces/AAAAAAAAAAA").
        filter: An optional filter query. Supported queries include matching by
               'createTime' (e.g., 'createTime > "2023-01-01T00:00:00Z"') or
               'thread.name' (e.g., 'thread.name = "spaces/XYZ/threads/ABC"').
        page_size: Maximum number of messages to return.
        page_token: A token for pagination, received from a previous list call.

    Returns:
        A dictionary containing the API response with matching messages.
    """
    service = get_chat_service()
    logger.debug(f"Listing messages in space '{space_id}' with filter: '{filter}'")
    return service.spaces().messages().list(
        parent=space_id,
        filter=filter,
        pageSize=page_size,
        pageToken=page_token
    ).execute()


@time_api_call
def search_messages(space_id: str, query: str, limit: int = 100) -> dict:
    """
    Search for messages in a Google Chat space containing specific text.
    
    NOTE: This performs a client-side search by fetching the most recent messages
    and filtering them in Python. It may be slow for deep searches.

    Args:
        space_id: The resource name of the space, e.g., "spaces/AAAAAAAAAAA".
        query: The text string to search for (case-insensitive).
        limit: The maximum number of recent messages to scan (default 100).

    Returns:
        A dictionary containing a list of matching messages and stats.
    """
    # Fetch messages in batches
    found_messages = []
    page_token = None
    messages_scanned = 0
    
    # We'll fetch in chunks of 100 (max allowed by API usually) or remaining limit
    while messages_scanned < limit:
        batch_size = min(100, limit - messages_scanned)
        response = list_messages(space_id=space_id, page_size=batch_size, page_token=page_token)
        
        messages = response.get('messages', [])
        if not messages:
            break
            
        messages_scanned += len(messages)
        
        # Filter locally
        for msg in messages:
            text = msg.get('text', '')
            if query.lower() in text.lower():
                import json
                print("DEBUG: Raw matching message:")
                print(json.dumps(msg, indent=2))
                
                # Resolve author name
                from gwsa.sdk.people import get_person_name
                sender = msg.get("sender", {})
                user_id = sender.get("name")
                author_name = get_person_name(user_id)
                
                found_messages.append({
                    "name": msg.get("name"),
                    "text": text,
                    "createTime": msg.get("createTime"),
                    "author": author_name,
                    "thread": msg.get("thread", {}).get("name")
                })
        
        page_token = response.get('nextPageToken')
        if not page_token:
            break
            
    return {
        "query": query,
        "scanned_count": messages_scanned,
        "matches_found": len(found_messages),
        "messages": found_messages
    }