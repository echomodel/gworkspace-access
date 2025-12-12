"""GWSA MCP Server - Exposes Google Workspace operations via MCP.

This server uses the GWSA SDK to provide Gmail and profile management
capabilities to MCP clients. It leverages whatever profile is currently
configured, just like the CLI.

Profile operations are read-only (no creation, no credential changes).
"""

import json
import logging
from typing import Optional, List

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from gwsa.sdk import profiles, mail, docs, auth

logger = logging.getLogger(__name__)

# Create the MCP server
mcp = FastMCP("gwsa")


# =============================================================================
# Profile Tools (read-only operations)
# =============================================================================

@mcp.tool()
async def list_profiles() -> str:
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
        return json.dumps(safe_profiles, indent=2)
    except Exception as e:
        logger.error(f"Error listing profiles: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_active_profile() -> str:
    """
    Get the currently active authentication profile.

    Returns the profile name and associated email address.
    Returns null if no profile is configured.
    """
    try:
        profile = profiles.get_active_profile()
        if profile:
            return json.dumps({
                "name": profile["name"],
                "email": profile.get("email"),
                "is_adc": profile["is_adc"],
            }, indent=2)
        return json.dumps(None)
    except Exception as e:
        logger.error(f"Error getting active profile: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def switch_profile(profile_name: str) -> str:
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
            return json.dumps({
                "error": f"Profile '{profile_name}' does not exist",
                "hint": "Available profiles can be listed with list_profiles"
            })

        success = profiles.set_active_profile(profile_name)
        if success:
            # Get the profile info to return
            profile = profiles.get_active_profile()
            return json.dumps({
                "success": True,
                "message": f"Switched to profile '{profile_name}'",
                "email": profile.get("email") if profile else None
            })
        else:
            return json.dumps({"error": "Failed to switch profile"})
    except Exception as e:
        logger.error(f"Error switching profile: {e}")
        return json.dumps({"error": str(e)})


# =============================================================================
# Mail Tools
# =============================================================================

@mcp.tool()
async def search_emails(
    query: str,
    max_results: int = 25,
    page_token: Optional[str] = None,
    format: str = "metadata"
) -> str:
    """
    Search Gmail messages using Gmail query syntax.

    Args:
        query: Gmail search query (e.g., "from:someone@example.com", "subject:invoice",
               "after:2024/01/01 before:2024/12/31", "label:important is:unread")
        max_results: Maximum number of messages to return (default 25, max 500)
        page_token: Pagination token from previous search result
        format: "metadata" (fast, headers only) or "full" (includes body, slower)

    Returns:
        JSON with list of messages and pagination info
    """
    try:
        messages, metadata = mail.search_messages(
            query=query,
            max_results=max_results,
            page_token=page_token,
            format=format
        )
        return json.dumps({
            "messages": messages,
            "resultSizeEstimate": metadata.get("resultSizeEstimate", 0),
            "nextPageToken": metadata.get("nextPageToken")
        }, indent=2)
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def read_email(message_id: str) -> str:
    """
    Read a specific email message by ID.

    Args:
        message_id: The Gmail message ID (obtained from search_emails)

    Returns:
        Full message content including subject, from, to, date, body (text and html),
        snippet, and labels
    """
    try:
        message = mail.read_message(message_id)
        # Remove raw field to reduce output size
        if "raw" in message:
            del message["raw"]
        return json.dumps(message, indent=2)
    except Exception as e:
        logger.error(f"Error reading email: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def add_email_label(message_id: str, label_name: str) -> str:
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
        return json.dumps({
            "success": True,
            "message_id": message_id,
            "label_added": label_name,
            "current_labels": result.get("labelIds", [])
        }, indent=2)
    except Exception as e:
        logger.error(f"Error adding label: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def remove_email_label(message_id: str, label_name: str) -> str:
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
        return json.dumps({
            "success": True,
            "message_id": message_id,
            "label_removed": label_name,
            "current_labels": result.get("labelIds", [])
        }, indent=2)
    except Exception as e:
        logger.error(f"Error removing label: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_email_labels() -> str:
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
        return json.dumps(simplified, indent=2)
    except Exception as e:
        logger.error(f"Error listing labels: {e}")
        return json.dumps({"error": str(e)})


# =============================================================================
# Docs Tools
# =============================================================================

@mcp.tool()
async def list_docs(max_results: int = 25, query: Optional[str] = None) -> str:
    """
    List Google Docs accessible to the current user.

    Args:
        max_results: Maximum number of documents to return (default 25)
        query: Optional search query to filter documents by title or content

    Returns:
        JSON with list of documents including id, title, url, and timestamps
    """
    try:
        result = docs.list_documents(max_results=max_results, query=query)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error listing docs: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def create_doc(title: str, body_text: Optional[str] = None) -> str:
    """
    Create a new Google Doc.

    Args:
        title: Title for the new document
        body_text: Optional initial body text to insert

    Returns:
        JSON with document id, title, and url
    """
    try:
        result = docs.create_document(title=title, body_text=body_text)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating doc: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def read_doc(doc_id: str, format: str = "content") -> str:
    """
    Read a Google Doc by ID.

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
            return json.dumps({"text": text}, indent=2)
        elif format == "raw":
            doc = docs.get_document(doc_id)
            return json.dumps(doc, indent=2)
        else:
            content = docs.get_document_content(doc_id)
            return json.dumps(content, indent=2)
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading doc: {e}")
            return json.dumps({
                "error": "The caller does not have permission.",
                "details": str(e),
                "hint": "The active gwsa profile may not have access to this document. "
                        "Try switching profiles with the `switch_profile` tool or "
                        "running `gwsa setup --new-user` to re-authenticate."
            })
        raise
    except Exception as e:
        logger.error(f"Error reading doc: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def append_to_doc(doc_id: str, text: str) -> str:
    """
    Append text to the end of a Google Doc.

    Args:
        doc_id: The Google Doc ID
        text: Text to append

    Returns:
        Success status and document revision info
    """
    try:
        result = docs.append_text(doc_id, text)
        return json.dumps({
            "success": True,
            "document_id": doc_id,
            "write_control": result.get("writeControl", {})
        }, indent=2)
    except Exception as e:
        logger.error(f"Error appending to doc: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def insert_in_doc(doc_id: str, text: str, index: int = 1) -> str:
    """
    Insert text at a specific position in a Google Doc.

    Args:
        doc_id: The Google Doc ID
        text: Text to insert
        index: Position to insert at (1 = beginning of document)

    Returns:
        Success status and document revision info
    """
    try:
        result = docs.insert_text(doc_id, text, index=index)
        return json.dumps({
            "success": True,
            "document_id": doc_id,
            "inserted_at_index": index,
            "write_control": result.get("writeControl", {})
        }, indent=2)
    except Exception as e:
        logger.error(f"Error inserting in doc: {e}")
        return json.dumps({"error": str(e)})


@mcp.tool()
async def replace_in_doc(
    doc_id: str,
    find_text: str,
    replace_with: str,
    match_case: bool = True
) -> str:
    """
    Replace all occurrences of text in a Google Doc.

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
        return json.dumps({
            "success": True,
            "document_id": doc_id,
            "occurrences_replaced": occurrences,
            "find_text": find_text,
            "replace_with": replace_with
        }, indent=2)
    except Exception as e:
        logger.error(f"Error replacing in doc: {e}")
        return json.dumps({"error": str(e)})


# =============================================================================
# Resources (read-only data access)
# =============================================================================

@mcp.resource("gwsa://profiles")
async def profiles_resource() -> str:
    """List of available authentication profiles."""
    return await list_profiles()


@mcp.resource("gwsa://labels")
async def labels_resource() -> str:
    """List of Gmail labels in the current account."""
    return await list_email_labels()


# =============================================================================
# Server entry point
# =============================================================================

def run_server():
    """Run the MCP server with stdio transport."""
    mcp.run()


if __name__ == "__main__":
    run_server()
