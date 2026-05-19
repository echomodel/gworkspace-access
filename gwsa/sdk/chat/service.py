"""Google Chat service factory for GWSA SDK."""

import logging
from typing import Any, Optional

from googleapiclient.discovery import build

from ..auth import get_credentials
from ..timing import time_api_call

logger = logging.getLogger(__name__)


def get_chat_service(account: Optional[str] = None) -> Any:
    """Build an authenticated Google Chat API service for the current user.

    Args:
        account: Optional selector — account name or Google email.
            Omit to use the user's default account.
    """
    creds, source = get_credentials(account=account)
    logger.debug(f"Building Chat service using credentials from: {source}")
    return build("chat", "v1", credentials=creds)

@time_api_call
def list_messages(
    space_id: str,
    filter: str = None,
    page_size: int = 25,
    page_token: str = None,
    account: Optional[str] = None,
) -> dict:
    """Lists messages in a Google Chat space, with optional filtering.

    NOTE: The filter only supports filtering by 'createTime' and 'thread.name'.
    It does NOT support full-text search.

    Args:
        space_id: The resource name of the space (e.g., "spaces/AAAAAAAAAAA").
        filter: An optional filter query. Supported queries include matching by
               'createTime' (e.g., 'createTime > "2023-01-01T00:00:00Z"') or
               'thread.name' (e.g., 'thread.name = "spaces/XYZ/threads/ABC"').
        page_size: Maximum number of messages to return.
        page_token: A token for pagination, received from a previous list call.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        A dictionary containing the API response with matching messages.
    """
    service = get_chat_service(account=account)
    logger.debug(f"Listing messages in space '{space_id}' with filter: '{filter}'")
    return service.spaces().messages().list(
        parent=space_id,
        filter=filter,
        pageSize=page_size,
        pageToken=page_token
    ).execute()


@time_api_call
def search_messages(
    space_id: str,
    query: str,
    limit: int = 100,
    account: Optional[str] = None,
) -> dict:
    """Search for messages in a Google Chat space containing specific text.

    NOTE: This performs a client-side search by fetching the most recent messages
    and filtering them in Python. It may be slow for deep searches.

    Args:
        space_id: The resource name of the space, e.g., "spaces/AAAAAAAAAAA".
        query: The text string to search for (case-insensitive).
        limit: The maximum number of recent messages to scan (default 100).
        account: Optional account selector — name or email. Omit to use
            the user's default account.

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
        response = list_messages(
            space_id=space_id,
            page_size=batch_size,
            page_token=page_token,
            account=account,
        )
        
        messages = response.get('messages', [])
        if not messages:
            break
            
        messages_scanned += len(messages)
        
        # Filter locally
        for msg in messages:
            text = msg.get('text', '')
            if query.lower() in text.lower():
                # Resolve author name
                from gwsa.sdk.people import get_person_name
                sender = msg.get("sender", {})
                user_id = sender.get("name")
                author_name = get_person_name(user_id, account=account)
                
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


def get_recent_chats(
    chat_type: str,
    limit: int = 10,
    account: Optional[str] = None,
) -> list:
    """List recent Chat spaces of a given type, sorted by last activity.

    Args:
        chat_type: Space type filter — "DIRECT_MESSAGE", "GROUP_CHAT",
            or "SPACE".
        limit: Maximum number of spaces to return.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        List of {id, displayName} dicts.
    """
    from ..people import get_person_name

    chat_service = get_chat_service(account=account)
    filter_query = f'space_type = "{chat_type}"'
    fields = (
        "nextPageToken,spaces(name,displayName,spaceType,"
        "lastActiveTime,membershipCount)"
    )

    all_spaces = []
    page_token = None
    while True:
        results = chat_service.spaces().list(
            pageSize=100,
            pageToken=page_token,
            filter=filter_query,
            fields=fields,
        ).execute()
        all_spaces.extend(results.get("spaces", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    sorted_spaces = sorted(
        all_spaces,
        key=lambda x: x.get("lastActiveTime", "1970-01-01T00:00:00Z"),
        reverse=True,
    )

    recent_chats = []
    for space in sorted_spaces[:limit]:
        display_name = space.get("displayName", "Unknown")

        if chat_type == "DIRECT_MESSAGE" and display_name == "Unknown":
            try:
                members_result = chat_service.spaces().members().list(
                    parent=space["name"], pageSize=2
                ).execute()
                members = members_result.get("memberships", [])
                if members:
                    other_member = members[0].get("member", {})
                    resolved_name = other_member.get("displayName")
                    if not resolved_name:
                        resolved_name = get_person_name(
                            other_member.get("name"), account=account
                        )
                    display_name = resolved_name
            except Exception:
                pass

        recent_chats.append({
            "id": space["name"],
            "displayName": display_name,
        })

    return recent_chats