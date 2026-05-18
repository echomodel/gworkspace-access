"""Google Chat MCP tools.

Plain async functions delegating to ``gwsa.sdk.chat`` and
``gwsa.sdk.people`` for member-name resolution.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from gwsa.sdk import chat
from gwsa.sdk.cache import get_cached_members, set_cached_members
from gwsa.sdk.people import get_person_name

logger = logging.getLogger(__name__)


async def list_chat_spaces(
    limit: int = 10,
    space_type: Optional[str] = None,
    verbose: bool = False,
    resolve_names: bool = False,
) -> dict[str, Any]:
    """List Google Chat spaces with filtering and optional detail.

    Args:
        limit: Max number of spaces to return (default 10).
        space_type: Optional filter — "DIRECT_MESSAGE", "GROUP_CHAT",
            or "SPACE".
        verbose: If True, returns all available metadata for each space
            (e.g., ``lastActiveTime``, ``membershipCount``).
        resolve_names: If True, resolves and includes participant first
            names for DMs and group chats (slower, results are cached).

    Returns:
        Dict with a ``spaces`` list. Default entries are
        ``{name, displayName, type}``; ``resolve_names=True`` replaces
        ``displayName`` with a comma-separated list of participant
        names; ``verbose=True`` returns the full API space objects,
        optionally enriched with ``participant_names``.
    """
    try:
        chat_service = chat.get_chat_service()
        filter_query = ""
        if space_type:
            filter_query = f'space_type = "{space_type.upper()}"'
        result = chat_service.spaces().list(
            pageSize=limit, filter=filter_query
        ).execute()
        spaces = result.get("spaces", [])

        if resolve_names:
            for space in spaces:
                if space.get("spaceType") in ("DIRECT_MESSAGE", "GROUP_CHAT"):
                    try:
                        members = get_cached_members(space["name"])
                        if not members:
                            members_result = chat_service.spaces().members().list(
                                parent=space["name"], pageSize=10
                            ).execute()
                            members = members_result.get("memberships", [])
                            set_cached_members(space["name"], members)
                        participant_names = [
                            get_person_name(m.get("member", {}).get("name")).split(" ")[0]
                            for m in members
                        ]
                        space["participant_names"] = ", ".join(participant_names)
                    except Exception as e:
                        logger.warning(
                            f"Could not resolve names for space {space['name']}: {e}"
                        )
                        space["participant_names"] = "Error"

        if not verbose:
            simplified = []
            for space in spaces:
                s = {
                    "name": space.get("name"),
                    "displayName": space.get("displayName", "Unknown"),
                    "type": space.get("spaceType"),
                }
                if "participant_names" in space:
                    s["displayName"] = space["participant_names"]
                simplified.append(s)
            return {"spaces": simplified}
        return {"spaces": spaces}
    except Exception as e:
        logger.error(f"Error listing chat spaces: {e}")
        return {"error": str(e)}


async def list_chat_members(space_id: str, limit: int = 100) -> dict[str, Any]:
    """List members of a Google Chat space (cached for name resolution).

    Args:
        space_id: Resource name of the space (e.g., "spaces/AAA...").
        limit: Maximum number of members to return (default 100).

    Returns:
        Dict with a ``members`` list, each member with ``name``,
        ``displayName``, and ``type``. Cached for repeat calls.
    """
    try:
        members = get_cached_members(space_id)
        if not members:
            chat_service = chat.get_chat_service()
            result = chat_service.spaces().members().list(
                parent=space_id, pageSize=limit
            ).execute()
            members = result.get("memberships", [])
            set_cached_members(space_id, members)

        simplified = []
        for m in members:
            member = m.get("member", {})
            user_id = member.get("name")
            display_name = member.get("displayName") or get_person_name(user_id)
            simplified.append({
                "name": user_id,
                "displayName": display_name,
                "type": member.get("type"),
            })
        return {"members": simplified}
    except Exception as e:
        logger.error(f"Error listing chat members for space {space_id}: {e}")
        return {"error": str(e)}


async def list_chat_messages(
    space_id: str,
    filter: Optional[str] = None,
    page_size: int = 25,
) -> dict[str, Any]:
    """List messages in a Google Chat space, with an optional filter.

    NOTE: The filter only supports ``createTime`` (e.g.,
    ``createTime > "2025-12-15T10:00:00Z"``) and ``thread.name``
    (e.g., ``thread.name = "spaces/XYZ/threads/ABC"``). It does NOT
    support full-text search.

    Args:
        space_id: Resource name of the space (e.g., "spaces/AAA...").
        filter: Optional filter query.
        page_size: Maximum number of messages to return.

    Returns:
        Dict with ``messages`` (each with ``name``, ``text``,
        ``createTime``, ``author``) and ``nextPageToken``.
    """
    try:
        chat_service = chat.get_chat_service()
        response = chat_service.spaces().messages().list(
            parent=space_id, filter=filter, pageSize=page_size
        ).execute()
        messages = response.get("messages", [])
        simplified = []
        for message in messages:
            sender = message.get("sender", {})
            simplified.append({
                "name": message.get("name"),
                "text": message.get("text"),
                "createTime": message.get("createTime"),
                "author": get_person_name(sender.get("name")),
            })
        return {
            "messages": simplified,
            "nextPageToken": response.get("nextPageToken"),
        }
    except Exception as e:
        logger.error(f"Error listing chat messages in space '{space_id}': {e}")
        return {"error": str(e)}


async def search_chat_messages(
    space_id: str,
    query: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Search for messages in a Google Chat space containing specific text.

    NOTE: Performs a client-side search by fetching the most recent
    ``limit`` messages and filtering them in Python. May be slow for
    deep searches.

    Args:
        space_id: Resource name of the space.
        query: Text to search for (case-insensitive).
        limit: Maximum number of recent messages to scan (default 100).

    Returns:
        Dict with ``messages`` (matched), ``scanned_count``, and
        ``matches_found``.
    """
    try:
        chat_service = chat.get_chat_service()
        results = chat_service.spaces().messages().list(
            parent=space_id, pageSize=limit
        ).execute()
        messages = results.get("messages", [])
        matches = [m for m in messages if query.lower() in m.get("text", "").lower()]
        simplified = []
        for msg in matches:
            simplified.append({
                "name": msg.get("name"),
                "text": msg.get("text"),
                "createTime": msg.get("createTime"),
                "author": get_person_name(msg.get("sender", {}).get("name")),
            })
        return {
            "messages": simplified,
            "scanned_count": len(messages),
            "matches_found": len(simplified),
        }
    except Exception as e:
        logger.error(f"Error searching chat messages in space '{space_id}': {e}")
        return {"error": str(e)}


async def get_recent_direct_messages(limit: int = 10) -> dict[str, Any]:
    """Get the most recent Direct Messages.

    Args:
        limit: Maximum number of recent DMs to return (default 10).

    Returns:
        Dict with a ``direct_messages`` list of recent DM spaces.
    """
    try:
        from gwsa.sdk.chat import get_recent_chats
        return {"direct_messages": get_recent_chats(
            chat_type="DIRECT_MESSAGE", limit=limit
        )}
    except Exception as e:
        logger.error(f"Error getting recent DMs: {e}")
        return {"error": str(e)}


async def get_recent_group_chats(limit: int = 10) -> dict[str, Any]:
    """Get the most recent group chats.

    Args:
        limit: Maximum number of recent group chats to return
            (default 10).

    Returns:
        Dict with a ``group_chats`` list of recent group chat spaces.
    """
    try:
        from gwsa.sdk.chat import get_recent_chats
        return {"group_chats": get_recent_chats(
            chat_type="GROUP_CHAT", limit=limit
        )}
    except Exception as e:
        logger.error(f"Error getting recent group chats: {e}")
        return {"error": str(e)}
