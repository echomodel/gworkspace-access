"""GWSA MCP Server - Exposes Google Workspace operations via MCP.

This server uses the GWSA SDK to provide Gmail and profile management
capabilities to MCP clients. It leverages whatever profile is currently
configured, just like the CLI.

Profile operations are read-only (no creation, no credential changes).
"""

import json
import logging
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from gwsa.sdk import profiles, mail, docs, drive, auth, chat
from gwsa.sdk.exceptions import LocalPathError, InvalidDocIdError

logger = logging.getLogger(__name__)

# Create the MCP server
mcp = FastMCP("gwsa")


@mcp.tool()
async def list_chat_spaces(
    limit: int = 10, 
    space_type: Optional[str] = None, 
    verbose: bool = False, 
    resolve_names: bool = False
) -> dict[str, Any]:
    """
    List Google Chat spaces with filtering and optional detailed output.

    This tool is the powerful equivalent of the 'gwsa chat spaces list' CLI command.
    By default, it returns a simple list of spaces. Use the optional flags to
    retrieve detailed metadata and participant names.

    Args:
        limit: Max number of spaces to return (default: 10).
        space_type: Optional. Filter by type: 'DIRECT_MESSAGE', 'GROUP_CHAT', 'SPACE'.
        verbose: Optional. If True, returns all available metadata for each space,
                 such as 'lastActiveTime' and 'membershipCount'.
        resolve_names: Optional. If True, resolves and includes participant first names
                       for DMs and group chats (slower, but results are cached).

    Returns:
        A dictionary containing a list of space objects. The level of detail in
        each object depends on the flags used.
        - Default: {"name", "displayName", "type"}
        - resolve_names=True: "displayName" is replaced with a comma-separated list of names.
        - verbose=True: The full, rich space object from the API is returned, potentially
          enriched with 'participant_names' if resolve_names is also True.

    Examples:
        # Get the 10 most recent spaces of any type
        list_chat_spaces()

        # Get the 5 most recent Direct Messages
        list_chat_spaces(limit=5, space_type='DIRECT_MESSAGE')

        # Get full details for the 10 most recent spaces, including member names
        list_chat_spaces(verbose=True, resolve_names=True)
    """
    try:
        chat_service = chat.get_chat_service()
        
        filter_query = ''
        if space_type:
            filter_query = f"space_type = \"{space_type.upper()}\""
            
        result = chat_service.spaces().list(pageSize=limit, filter=filter_query).execute()
        spaces = result.get('spaces', [])

        if resolve_names:
            from gwsa.sdk.people import get_person_name
            from gwsa.sdk.cache import get_cached_members, set_cached_members
            for space in spaces:
                if space.get('spaceType') in ['DIRECT_MESSAGE', 'GROUP_CHAT']:
                    try:
                        members = get_cached_members(space['name'])
                        if not members:
                            members_result = chat_service.spaces().members().list(parent=space['name'], pageSize=10).execute()
                            members = members_result.get('memberships', [])
                            set_cached_members(space['name'], members)
                        
                        participant_names = [
                            get_person_name(m.get('member', {}).get('name')).split(' ')[0]
                            for m in members
                        ]
                        space['participant_names'] = ", ".join(participant_names)
                    except Exception as e:
                        logger.warning(f"Could not resolve names for space {space['name']}: {e}")
                        space['participant_names'] = "Error"

        # If not verbose, return a simplified list. Otherwise, return the full objects.
        if not verbose:
            simplified_spaces = []
            for space in spaces:
                s = {
                    "name": space.get("name"),
                    "displayName": space.get("displayName", "Unknown"),
                    "type": space.get("spaceType"),
                }
                if 'participant_names' in space:
                    s['displayName'] = space['participant_names']
                simplified_spaces.append(s)
            return {"spaces": simplified_spaces}
        else:
            # For verbose output, just return the full (and potentially enriched) space objects
            return {"spaces": spaces}

    except Exception as e:
        logger.error(f"Error listing chat spaces: {e}")
        return {"error": str(e)}


@mcp.tool()
async def list_chat_members(space_id: str, limit: int = 100) -> dict[str, Any]:
    """
    List members of a Google Chat space, using a cache for name resolution.

    Args:
        space_id: The resource name of the space (e.g., "spaces/AAA...").
        limit: Maximum number of members to return (default 100).

    Returns:
        Dict with a list of members, including their resource name, display name, and type.
        Results are cached to improve performance on subsequent calls for the same space.
    """
    try:
        from gwsa.sdk.people import get_person_name
        from gwsa.sdk.cache import get_cached_members, set_cached_members

        members = get_cached_members(space_id)
        if not members:
            chat_service = chat.get_chat_service()
            result = chat_service.spaces().members().list(parent=space_id, pageSize=limit).execute()
            members = result.get('memberships', [])
            set_cached_members(space_id, members)
        
        simplified_members = []
        for m in members:
            member = m.get('member', {})
            user_id = member.get('name')
            # The member object from the Chat API often has a displayName.
            # We fall back to our cached People API lookup if it's missing.
            display_name = member.get('displayName') or get_person_name(user_id)
                
            simplified_members.append({
                "name": user_id,
                "displayName": display_name,
                "type": member.get("type"),
            })
            
        return {"members": simplified_members}
    except Exception as e:
        logger.error(f"Error listing chat members for space {space_id}: {e}")
        return {"error": str(e)}



@mcp.tool()
async def list_chat_messages(space_id: str, filter: str = None, page_size: int = 25) -> dict[str, Any]:
    """
    Lists messages in a Google Chat space, with an optional filter.

    NOTE: The filter only supports filtering by 'createTime' (e.g., 'createTime > "2025-12-15T10:00:00Z"')
    and 'thread.name' (e.g., 'thread.name = "spaces/XYZ/threads/ABC"'). It does NOT support full-text search.

    Args:
        space_id: The resource name of the space, e.g., "spaces/AAAAAAAAAAA".
        filter: Optional. The filter query to apply.
        page_size: The maximum number of messages to return.

    Returns:
        A dictionary containing a list of matching messages with their name, text, createTime, and author, along with a nextPageToken if more results are available.
    """
    try:
        chat_service = chat.get_chat_service()
        response = chat_service.spaces().messages().list(parent=space_id, filter=filter, pageSize=page_size).execute()
        
        # Simplify the output for clarity
        from gwsa.sdk.people import get_person_name
        
        messages = response.get('messages', [])
        simplified_messages = []
        for message in messages:
            sender = message.get("sender", {})
            user_id = sender.get("name")
            author_name = get_person_name(user_id)
            
            simplified_messages.append({
                "name": message.get("name"),
                "text": message.get("text"),
                "createTime": message.get("createTime"),
                "author": author_name,
            })
        
        return {
            "messages": simplified_messages,
            "nextPageToken": response.get("nextPageToken"),
        }
    except Exception as e:
        logger.error(f"Error listing chat messages in space '{space_id}': {e}")
        return {"error": str(e)}


@mcp.tool()
async def search_chat_messages(space_id: str, query: str, limit: int = 100) -> dict[str, Any]:
    """
    Search for messages in a Google Chat space containing specific text.
    
    NOTE: This performs a client-side search by fetching the most recent messages
    and filtering them in Python. It may be slow for deep searches.

    Args:
        space_id: The resource name of the space, e.g., "spaces/AAAAAAAAAAA".
        query: The text string to search for (case-insensitive).
        limit: The maximum number of recent messages to scan (default 100).

    Returns:
        A dictionary containing a list of matching messages.
    """
    try:
        chat_service = chat.get_chat_service()
        results = chat_service.spaces().messages().list(parent=space_id, pageSize=limit).execute()
        messages = results.get('messages', [])
        
        matches = [msg for msg in messages if query.lower() in msg.get('text', '').lower()]
        
        from gwsa.sdk.people import get_person_name
        
        simplified_messages = []
        for msg in matches:
            author_name = get_person_name(msg.get('sender', {}).get('name'))
            simplified_messages.append({
                "name": msg.get("name"),
                "text": msg.get("text"),
                "createTime": msg.get("createTime"),
                "author": author_name,
            })

        return {
            "messages": simplified_messages,
            "scanned_count": len(messages),
            "matches_found": len(simplified_messages),
        }
    except Exception as e:
        logger.error(f"Error searching chat messages in space '{space_id}': {e}")
        return {"error": str(e)}


@mcp.tool()
async def get_recent_direct_messages(limit: int = 10) -> dict[str, Any]:
    """
    Get the most recent Direct Messages (DMs).

    This is more convenient than filtering all spaces. It returns a sorted list
    of the most recent DMs.

    Args:
        limit: The maximum number of recent DMs to return.

    Returns:
        A dictionary containing a list of the most recent DM spaces.
    """
    try:
        from gwsa.sdk.chat import get_recent_chats
        chats = get_recent_chats(chat_type='DIRECT_MESSAGE', limit=limit)
        return {"direct_messages": chats}
    except Exception as e:
        logger.error(f"Error getting recent DMs: {e}")
        return {"error": str(e)}


@mcp.tool()
async def get_recent_group_chats(limit: int = 10) -> dict[str, Any]:
    """
    Get the most recent Group Chats.

    This is more convenient than filtering all spaces. It returns a sorted list
    of the most recent group chats.

    Args:
        limit: The maximum number of recent group chats to return.

    Returns:
        A dictionary containing a list of the most recent group chat spaces.
    """
    try:
        from gwsa.sdk.chat import get_recent_chats
        chats = get_recent_chats(chat_type='GROUP_CHAT', limit=limit)
        return {"group_chats": chats}
    except Exception as e:
        logger.error(f"Error getting recent group chats: {e}")
        return {"error": str(e)}


# =============================================================================
# Profile Tools (read-only operations)
# =============================================================================

@mcp.tool()
async def list_profiles() -> list[dict[str, Any]]:
    """
    List all available authentication profiles.

    Returns profiles including:
    - name: Profile identifier
    - email: Associated Google account email
    - is_active: Whether this is the currently active profile
    - is_adc: Whether this uses Application Default Credentials

    Use switch_profile to change the active profile.
    """
    try:
        profile_list = profiles.list_profiles()
        # Filter out sensitive info, keep only what's needed
        safe_profiles = []
        for p in profile_list:
            safe_profiles.append({
                "name": p["name"],
                "email": p.get("email"),
                "is_active": p["is_active"],
                "is_adc": p["is_adc"],
                "last_validated": p.get("last_validated"),
            })
        return safe_profiles
    except Exception as e:
        logger.error(f"Error listing profiles: {e}")
        return [{"error": str(e)}]


@mcp.tool()
async def get_active_profile() -> Optional[dict[str, Any]]:
    """
    Get the currently active authentication profile.

    Returns the profile name and associated email address.
    Returns null if no profile is configured.
    """
    try:
        profile = profiles.get_active_profile()
        if profile:
            return {
                "name": profile["name"],
                "email": profile.get("email"),
                "is_adc": profile["is_adc"],
            }
        return None
    except Exception as e:
        logger.error(f"Error getting active profile: {e}")
        return {"error": str(e)}


@mcp.tool()
async def switch_profile(profile_name: str) -> dict[str, Any]:
    """
    Switch to a different authentication profile.

    This changes which Google account is used for subsequent operations.
    The profile must already exist (use 'gwsa profiles list' in CLI to see available profiles).

    Args:
        profile_name: Name of the profile to switch to (e.g., "default", "work", "adc")

    Returns:
        Success message or error if profile doesn't exist
    """
    try:
        if not profiles.profile_exists(profile_name):
            return {
                "error": f"Profile '{profile_name}' does not exist",
                "hint": "Available profiles can be listed with list_profiles"
            }

        success = profiles.set_active_profile(profile_name)
        if success:
            # Get the profile info to return
            profile = profiles.get_active_profile()
            return {
                "success": True,
                "message": f"Switched to profile '{profile_name}'",
                "email": profile.get("email") if profile else None
            }
        else:
            return {"error": "Failed to switch profile"}
    except Exception as e:
        logger.error(f"Error switching profile: {e}")
        return {"error": str(e)}


# =============================================================================
# Mail Tools
# =============================================================================

@mcp.tool()
async def search_emails(
    query: str,
    max_results: int = 25,
    page_token: Optional[str] = None,
    format: str = "metadata"
) -> dict[str, Any]:
    """
    Search Gmail messages using Gmail query syntax.

    Args:
        query: Gmail search query (e.g., "from:user@example.com", "subject:invoice",
               "after:2024/01/01 before:2024/12/31", "label:important is:unread")
        max_results: Maximum number of messages to return (default 25, max 500)
        page_token: Pagination token from previous search result
        format: "metadata" (fast, headers only) or "full" (includes body, slower)

    Returns:
        Dict with list of messages and pagination info
    """
    try:
        messages, metadata = mail.search_messages(
            query=query,
            max_results=max_results,
            page_token=page_token,
            format=format
        )
        return {
            "messages": messages,
            "resultSizeEstimate": metadata.get("resultSizeEstimate", 0),
            "nextPageToken": metadata.get("nextPageToken")
        }
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        return {"error": str(e)}


@mcp.tool()
async def read_email(message_id: str) -> dict[str, Any]:
    """
    Read a specific email message by ID.

    Args:
        message_id: The Gmail message ID (obtained from search_emails)

    Returns:
        Full message content including subject, from, to, date, body (text and html),
        snippet, labels, and attachments (with filename, mimeType, size, attachmentId)
    """
    try:
        message = mail.read_message(message_id)
        # Remove raw field to reduce output size
        if "raw" in message:
            del message["raw"]
        return message
    except Exception as e:
        logger.error(f"Error reading email: {e}")
        return {"error": str(e)}


@mcp.tool()
async def add_email_label(message_id: str, label_name: str) -> dict[str, Any]:
    """
    Add a label to an email message.

    If the label doesn't exist, it will be created automatically.

    Args:
        message_id: The Gmail message ID
        label_name: Name of the label to add (e.g., "Important", "ToReview")

    Returns:
        Updated message with new labels
    """
    try:
        result = mail.add_label(message_id, label_name)
        return {
            "success": True,
            "message_id": message_id,
            "label_added": label_name,
            "current_labels": result.get("labelIds", [])
        }
    except Exception as e:
        logger.error(f"Error adding label: {e}")
        return {"error": str(e)}


@mcp.tool()
async def remove_email_label(message_id: str, label_name: str) -> dict[str, Any]:
    """
    Remove a label from an email message.

    Args:
        message_id: The Gmail message ID
        label_name: Name of the label to remove

    Returns:
        Updated message with remaining labels
    """
    try:
        result = mail.remove_label(message_id, label_name)
        return {
            "success": True,
            "message_id": message_id,
            "label_removed": label_name,
            "current_labels": result.get("labelIds", [])
        }
    except Exception as e:
        logger.error(f"Error removing label: {e}")
        return {"error": str(e)}


@mcp.tool()
async def list_email_labels() -> list[dict[str, Any]]:
    """
    List all Gmail labels available in the current account.

    Returns:
        List of labels with their IDs, names, and types (system or user)
    """
    try:
        labels = mail.list_labels()
        # Simplify output
        simplified = []
        for label in labels:
            simplified.append({
                "id": label["id"],
                "name": label["name"],
                "type": label.get("type", "user")
            })
        return simplified
    except Exception as e:
        logger.error(f"Error listing labels: {e}")
        return [{"error": str(e)}]


@mcp.tool()
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
) -> dict[str, Any]:
    """
    Send an email via Gmail.

    Args:
        to: Recipient email address (comma-separated for multiple recipients)
        subject: Email subject line
        body: Plain text body of the email
        cc: Optional CC recipients (comma-separated)
        bcc: Optional BCC recipients (comma-separated)

    Returns:
        Dict with message ID and thread ID of the sent email
    """
    try:
        result = mail.send_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
        )
        return {
            "success": True,
            "message_id": result.get("id"),
            "thread_id": result.get("threadId"),
            "message": f"Email sent successfully to {to}",
        }
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def reply_email(
    message_id: str,
    body: str,
    include_quote: bool = True,
    as_draft: bool = False,
) -> dict[str, Any]:
    """
    Reply to an email message, properly threaded with quoted content.

    Args:
        message_id: The Gmail message ID to reply to (from search_emails or read_email)
        body: Plain text body of your reply
        include_quote: Include quoted original message (default True)
        as_draft: Create a draft instead of sending immediately (default False)

    Returns:
        Dict with message/draft ID, thread ID, and success status
    """
    try:
        result = mail.reply_message(
            reply_to_message_id=message_id,
            body=body,
            include_quote=include_quote,
            as_draft=as_draft,
        )
        return {
            "success": True,
            "id": result.get("id"),
            "thread_id": result.get("threadId"),
            "is_draft": result.get("is_draft", False),
            "message": "Reply draft created" if result.get("is_draft") else "Reply sent successfully",
        }
    except Exception as e:
        logger.error(f"Error replying to email: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def download_email_attachment(
    message_id: str,
    attachment_id: str,
    save_path: str
) -> dict[str, Any]:
    """
    Download an email attachment and save it to a local file.

    Args:
        message_id: The Gmail message ID containing the attachment
        attachment_id: The attachment ID (from read_email attachments list)
        save_path: Local file path where the attachment should be saved

    Returns:
        Dict with success status, file path, and size in bytes
    """
    try:
        result = mail.get_attachment(message_id, attachment_id)
        data = result['data']
        size = result['size']

        # Write the binary data to the specified path
        with open(save_path, 'wb') as f:
            f.write(data)

        return {
            "success": True,
            "message_id": message_id,
            "attachment_id": attachment_id,
            "saved_to": save_path,
            "size_bytes": size
        }
    except Exception as e:
        logger.error(f"Error downloading attachment: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_email_thread(thread_id: str) -> dict[str, Any]:
    """
    Retrieve a full Gmail thread, including all its messages.

    Args:
        thread_id: The Gmail thread ID.

    Returns:
        Dict containing thread details, with a list of simplified messages.
    """
    try:
        thread = mail.get_thread(thread_id=thread_id)
        return thread
    except Exception as e:
        logger.error(f"Error getting email thread '{thread_id}': {e}")
        return {"error": str(e)}


# =============================================================================
# Docs Tools
# =============================================================================

@mcp.tool()
async def list_docs(max_results: int = 25, query: Optional[str] = None) -> dict[str, Any]:
    """
    NOTE: This tool works ONLY with remote Google Docs resources in the cloud.

    Args:
        max_results: Maximum number of documents to return (default 25)
        query: Optional search query to filter documents by title or content

    Returns:
        Dict with list of documents including id, title, url, and timestamps
    """
    try:
        result = docs.list_documents(max_results=max_results, query=query)
        return result
    except Exception as e:
        logger.error(f"Error listing docs: {e}")
        return {"error": str(e)}


@mcp.tool()
async def create_doc(
    title: str,
    body_text: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create a new Google Doc in the cloud.

    NOTE: This tool works ONLY with remote Google Docs resources in the cloud.

    Args:
        title: Title for the new document
        body_text: Optional initial body text to insert
        folder_id: Optional folder ID to create the doc in (default: My Drive root)

    Returns:
        Dict with document id, title, and url
    """
    try:
        result = docs.create_document(title=title, body_text=body_text, folder_id=folder_id)
        return result
    except Exception as e:
        logger.error(f"Error creating doc: {e}")
        return {"error": str(e)}


@mcp.tool()
async def read_doc(doc_id: str, format: str = "content") -> dict[str, Any]:
    """
    Read a Google Doc by ID.

    NOTE: This tool works ONLY with remote Google Docs resources in the cloud.

    Args:
        doc_id: The Google Doc ID
        format: "content" for metadata + text, "text" for plain text only,
                "raw" for full API response

    Returns:
        Document content in requested format
    """
    try:
        if format == "text":
            text = docs.get_document_text(doc_id)
            return {"text": text}
        elif format == "raw":
            doc = docs.get_document(doc_id)
            return doc
        else:
            content = docs.get_document_content(doc_id)
            return content
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except ValueError as e:
        logger.error(f"ValueError reading doc: {e}")
        return {"error": str(e)}
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading doc: {e}")
            return {
                "error": "The caller does not have permission.",
                "details": str(e),
                "hint": "The active gwsa profile may not have access to this document. "
                        "Try switching profiles with the `switch_profile` tool or "
                        "running `gwsa setup --new-user` to re-authenticate."
            }
        raise
    except Exception as e:
        logger.error(f"Error reading doc: {e}")
        return {"error": str(e)}


@mcp.tool()
async def append_to_doc(doc_id: str, text: str) -> dict[str, Any]:
    """
    Append text to the end of a Google Doc.

    NOTE: This tool works ONLY with remote Google Docs resources in the cloud.

    Args:
        doc_id: The Google Doc ID
        text: Text to append

    Returns:
        Success status and document revision info
    """
    try:
        result = docs.append_text(doc_id, text)
        return {
            "success": True,
            "document_id": doc_id,
            "write_control": result.get("writeControl", {})
        }
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error appending to doc: {e}")
        return {"error": str(e)}


@mcp.tool()
async def insert_in_doc(doc_id: str, text: str, index: int = 1) -> dict[str, Any]:
    """
    Insert text at a specific position in a Google Doc.

    NOTE: This tool works ONLY with remote Google Docs resources in the cloud.

    Args:
        doc_id: The Google Doc ID
        text: Text to insert
        index: Position to insert at (1 = beginning of document)

    Returns:
        Success status and document revision info
    """
    try:
        result = docs.insert_text(doc_id, text, index=index)
        return {
            "success": True,
            "document_id": doc_id,
            "inserted_at_index": index,
            "write_control": result.get("writeControl", {})
        }
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error inserting in doc: {e}")
        return {"error": str(e)}


@mcp.tool()
async def replace_in_doc(
    doc_id: str,
    find_text: str,
    replace_with: str,
    match_case: bool = True
) -> dict[str, Any]:
    """
    Replace all occurrences of text in a Google Doc.

    NOTE: This tool works ONLY with remote Google Docs resources in the cloud.

    Args:
        doc_id: The Google Doc ID
        find_text: Text to find
        replace_with: Text to replace with
        match_case: Whether to match case (default True)

    Returns:
        Number of occurrences replaced
    """
    try:
        result = docs.replace_text(doc_id, find_text, replace_with, match_case=match_case)
        replies = result.get("replies", [])
        occurrences = 0
        if replies:
            occurrences = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        return {
            "success": True,
            "document_id": doc_id,
            "occurrences_replaced": occurrences,
            "find_text": find_text,
            "replace_with": replace_with
        }
    except (LocalPathError, InvalidDocIdError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error replacing in doc: {e}")
        return {"error": str(e)}


# =============================================================================
# Drive Tools
# =============================================================================

@mcp.tool()
async def drive_list_folder(
    folder_id: Optional[str] = None,
    max_results: int = 100
) -> dict[str, Any]:
    """
    List contents of a Google Drive folder.

    Args:
        folder_id: Folder ID to list. Use None for My Drive root.
        max_results: Maximum number of items to return (default 100)

    Returns:
        Dict with list of files/folders including id, name, type, mime_type, modified_time, size.
        For shortcuts (mime_type: application/vnd.google-apps.shortcut), also includes
        target_id and target_mime_type - use target_id with drive_download to get the actual file.
    """
    try:
        result = drive.list_folder(folder_id=folder_id, max_results=max_results)
        return result
    except Exception as e:
        logger.error(f"Error listing folder: {e}")
        return {"error": str(e)}


@mcp.tool()
async def drive_create_folder(
    name: str,
    parent_id: Optional[str] = None
) -> dict[str, Any]:
    """
    Create a new folder in Google Drive.

    Args:
        name: Name for the new folder
        parent_id: Parent folder ID. Use None for My Drive root.

    Returns:
        Dict with folder id, name, and url
    """
    try:
        result = drive.create_folder(name=name, parent_id=parent_id)
        return result
    except Exception as e:
        logger.error(f"Error creating folder: {e}")
        return {"error": str(e)}


@mcp.tool()
async def drive_upload(
    local_path: str,
    folder_id: Optional[str] = None,
    name: Optional[str] = None
) -> dict[str, Any]:
    """
    Upload a file to Google Drive.

    Args:
        local_path: Absolute path to the local file to upload
        folder_id: Destination folder ID. Use None for My Drive root.
        name: Name for the file in Drive. Defaults to local filename.

    Returns:
        Dict with file id, name, and url
    """
    try:
        result = drive.upload_file(local_path=local_path, folder_id=folder_id, name=name)
        return result
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return {"error": str(e)}


@mcp.tool()
async def drive_update(
    file_id: str,
    local_path: str,
    name: Optional[str] = None
) -> dict[str, Any]:
    """
    Update an existing file in Google Drive.

    Args:
        file_id: The ID of the file to update.
        local_path: Absolute path to the local file content.
        name: Optional new name for the file.

    Returns:
        Dict with updated file metadata.
    """
    try:
        result = drive.update_file(file_id=file_id, local_path=local_path, new_name=name)
        return result
    except Exception as e:
        logger.error(f"Error updating file: {e}")
        return {"error": str(e)}


@mcp.tool()
async def drive_download(
    file_id: str,
    save_path: str
) -> dict[str, Any]:
    """
    Download a file from Google Drive.

    Args:
        file_id: The Drive file ID to download
        save_path: Local path where the file should be saved

    Returns:
        Dict with success status, file path, and size in bytes
    """
    try:
        result = drive.download_file(file_id=file_id, save_path=save_path)
        return result
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return {"error": str(e)}


@mcp.tool()
async def drive_find_folder(
    path: str,
    drive_id: str = "my_drive",
    folder_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Find a folder by navigating a path from a starting location.

    Args:
        path: Folder path with '/' separators (e.g., 'Projects/my-project')
        drive_id: Starting drive - "my_drive" (default) or a Shared Drive ID.
                  Ignored if folder_id is provided.
        folder_id: Start from this folder ID instead of a drive root.

    Returns:
        Dict with folder id, name, and path. Returns error if not found or ambiguous.
    """
    try:
        result = drive.find_folder_by_path(path, drive=drive_id, folder_id=folder_id)
        if result:
            return result
        return {"error": f"Folder not found: {path}"}
    except drive.AmbiguousFolderError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error finding folder: {e}")
        return {"error": str(e)}


@mcp.tool()
async def drive_search_folders(
    name: str,
    match: str = "contains",
    limit: int = 50,
) -> dict[str, Any]:
    """
    Search for folders by name across all accessible locations.

    Single API call. Searches My Drive, Shared Drives, and shared-with-me folders.

    Args:
        name: Folder name to search for.
        match: "contains" (default) or "exact" match. Case-insensitive.
        limit: Maximum results to return (default 50).

    Returns:
        Dict with 'folders' list. Each folder has: id, name, parents (list of IDs),
        created_time, modified_time, drive_id (None if in My Drive).
    """
    try:
        if match not in ("contains", "exact"):
            return {"error": f"Invalid match type: {match}. Use 'contains' or 'exact'."}
        results = drive.search_folders(name, match=match, limit=limit)
        return {"folders": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Error searching folders: {e}")
        return {"error": str(e)}


# =============================================================================
# Resources (read-only data access)
# =============================================================================

@mcp.resource("gwsa://profiles")
async def profiles_resource() -> str:
    """List of available authentication profiles."""
    result = await list_profiles()
    return json.dumps(result, indent=2)


@mcp.resource("gwsa://labels")
async def labels_resource() -> str:
    """List of Gmail labels in the current account."""
    result = await list_email_labels()
    return json.dumps(result, indent=2)


# =============================================================================
# Server entry point
# =============================================================================

def run_server():
    """Run the MCP server with stdio transport."""
    mcp.run()


if __name__ == "__main__":
    run_server()