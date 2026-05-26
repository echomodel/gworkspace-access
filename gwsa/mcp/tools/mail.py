"""Gmail MCP tools.

Plain async functions; mcp-app discovers them automatically. Each
tool delegates to ``gwsa.sdk.mail`` — the SDK is the single point of
credential resolution and Google API access.

Every tool accepts an optional ``account`` parameter: pass either
the account ``name`` (e.g. ``"work"``) or its Google ``email`` (e.g.
``"alice@example.com"``) to operate as a specific account on the
current user's profile. Omit to use the user's ``default_account``
(or the sole account if only one is configured). Use the
``list_google_accounts`` tool to discover available account names
and emails.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from gwsa.sdk import mail
from gwsa.sdk.destinations import (
    Destination,
    DriveDestination,
    InlinePayload,
    InlineTooLargeError,
    materialize,
)
from gwsa.mcp.content import (
    ContentBlock,
    drive_upload_to_dict,
    inline_payload_to_blocks,
)

logger = logging.getLogger(__name__)


async def search_emails(
    query: str,
    max_results: int = 25,
    page_token: Optional[str] = None,
    format: str = "metadata",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Search Gmail messages using Gmail query syntax.

    Args:
        query: Gmail search query (e.g., "from:user@example.com",
            "subject:invoice", "after:2024/01/01 before:2024/12/31",
            "label:important is:unread").
        max_results: Maximum number of messages to return
            (default 25, max 500).
        page_token: Pagination token from a previous search result.
        format: "metadata" (fast, headers only) or "full" (includes
            body, slower).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``messages``, ``resultSizeEstimate``, and
        ``nextPageToken``. On error returns ``{"error": str}``.
    """
    try:
        messages, metadata = mail.search_messages(
            query=query,
            max_results=max_results,
            page_token=page_token,
            format=format,
            account=account,
        )
        return {
            "messages": messages,
            "resultSizeEstimate": metadata.get("resultSizeEstimate", 0),
            "nextPageToken": metadata.get("nextPageToken"),
        }
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        return {"error": str(e)}


async def read_email(
    message_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Read a specific Gmail message by ID.

    Args:
        message_id: Gmail message ID (from ``search_emails``).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Full message content: subject, from, to, date, body
        (text and html), snippet, labels, and attachments. The
        ``raw`` field is stripped to reduce payload size.
    """
    try:
        message = mail.read_message(message_id, account=account)
        if "raw" in message:
            del message["raw"]
        return message
    except Exception as e:
        logger.error(f"Error reading email: {e}")
        return {"error": str(e)}


async def add_email_label(
    message_id: str,
    label_name: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Add a label to a Gmail message. Creates the label if missing.

    Args:
        message_id: Gmail message ID.
        label_name: Label name (e.g., "Important", "ToReview").
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``success``, ``message_id``, ``label_added``, and
        ``current_labels``.
    """
    try:
        result = mail.add_label(message_id, label_name, account=account)
        return {
            "success": True,
            "message_id": message_id,
            "label_added": label_name,
            "current_labels": result.get("labelIds", []),
        }
    except Exception as e:
        logger.error(f"Error adding label: {e}")
        return {"error": str(e)}


async def remove_email_label(
    message_id: str,
    label_name: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Remove a label from a Gmail message.

    Args:
        message_id: Gmail message ID.
        label_name: Label name to remove.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``success``, ``message_id``, ``label_removed``, and
        ``current_labels``.
    """
    try:
        result = mail.remove_label(message_id, label_name, account=account)
        return {
            "success": True,
            "message_id": message_id,
            "label_removed": label_name,
            "current_labels": result.get("labelIds", []),
        }
    except Exception as e:
        logger.error(f"Error removing label: {e}")
        return {"error": str(e)}


async def list_email_labels(
    account: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List all Gmail labels available for the chosen account.

    Args:
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        List of labels with ``id``, ``name``, and ``type``
        (``system`` or ``user``). On error returns a single-element
        list with an ``error`` key.
    """
    try:
        labels = mail.list_labels(account=account)
        return [
            {
                "id": label["id"],
                "name": label["name"],
                "type": label.get("type", "user"),
            }
            for label in labels
        ]
    except Exception as e:
        logger.error(f"Error listing labels: {e}")
        return [{"error": str(e)}]


async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Send an email via Gmail.

    Args:
        to: Recipient email (comma-separated for multiple).
        subject: Email subject line.
        body: Plain text body.
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).
        html_body: Optional HTML body.
        account: Optional account selector (name or email). Omit to
            send as the user's default account.

    Returns:
        Dict with ``success``, ``message_id``, ``thread_id``, and
        ``message`` describing the result.
    """
    try:
        result = mail.send_message(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, html_body=html_body,
            account=account,
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


async def reply_email(
    message_id: str,
    body: str,
    include_quote: bool = True,
    as_draft: bool = False,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Reply to a Gmail message, properly threaded with quoted content.

    Args:
        message_id: Gmail message ID to reply to.
        body: Plain text reply body.
        include_quote: Include quoted original message (default True).
        as_draft: Create a draft instead of sending (default False).
        account: Optional account selector (name or email). Omit to
            reply as the user's default account.

    Returns:
        Dict with ``success``, ``id``, ``thread_id``, ``is_draft``,
        and ``message``.
    """
    try:
        result = mail.reply_message(
            reply_to_message_id=message_id,
            body=body,
            include_quote=include_quote,
            as_draft=as_draft,
            account=account,
        )
        return {
            "success": True,
            "id": result.get("id"),
            "thread_id": result.get("threadId"),
            "is_draft": result.get("is_draft", False),
            "message": (
                "Reply draft created"
                if result.get("is_draft")
                else "Reply sent successfully"
            ),
        }
    except Exception as e:
        logger.error(f"Error replying to email: {e}")
        return {"success": False, "error": str(e)}


async def create_email_draft(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Gmail draft.

    Args:
        to: Recipient email (comma-separated for multiple).
        subject: Email subject line.
        body: Plain text body.
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).
        html_body: Optional HTML body.
        account: Optional account selector (name or email). Omit to
            create the draft in the user's default account.

    Returns:
        Dict with ``success``, ``draft_id``, and ``message``.
    """
    try:
        result = mail.create_draft(
            to=to, subject=subject, body=body,
            cc=cc, bcc=bcc, html_body=html_body,
            account=account,
        )
        return {
            "success": True,
            "draft_id": result.get("id"),
            "message": "Draft created successfully",
        }
    except Exception as e:
        logger.error(f"Error creating email draft: {e}")
        return {"success": False, "error": str(e)}


async def download_email_attachment(
    message_id: str,
    attachment_id: str,
    destination: Destination = DriveDestination(),
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
    account: Optional[str] = None,
) -> list[ContentBlock] | dict[str, Any]:
    """Download a Gmail attachment to a destination the agent can reach.

    The ``destination`` parameter is a discriminated union; pass one of:

    - ``{"kind": "drive", "folder_id": "<id>", "name": "<name>"}`` —
      upload to the user's Google Drive (default: My Drive root, with
      the attachment's original filename). Returns ``{drive_file_id,
      drive_url, name, mime_type, size_bytes, folder_id}``. Recommended
      default; works under any transport.
    - ``{"kind": "inline", "max_size_bytes": <int>}`` — return the
      bytes inline as an ``EmbeddedResource`` paired with a JSON
      summary. Best for small payloads the agent consumes immediately
      (default cap: 60,000 bytes — see :data:`gwsa.sdk.destinations.\
DEFAULT_INLINE_SIZE_CAP_BYTES` for the rationale). Larger payloads
      return an error envelope suggesting the Drive destination.

    Replaces the prior ``save_path: str`` signature, which only worked
    when the MCP was deployed stdio next to the agent. The new shape
    works under any transport because the response carries either the
    bytes themselves (inline) or a Drive reference the user already
    has tools to reach.

    Args:
        message_id: Gmail message ID containing the attachment.
        attachment_id: Attachment ID (from ``read_email``).
        destination: Where to deliver the bytes. See above.
        filename: Original attachment filename, as reported by
            ``read_email``. Always pass this when you have it — Gmail
            re-issues attachment IDs across ``messages.get`` requests,
            so a server-side lookup is unreliable. Without an explicit
            ``filename``, the Drive copy gets a generic
            ``attachment-<id-prefix>`` name.
        mime_type: Original attachment MIME type, as reported by
            ``read_email``. Same reliability concern as ``filename`` —
            pass it explicitly when you have it. Without an explicit
            ``mime_type``, the upload uses ``application/octet-stream``
            and Drive will sniff the real type from the bytes, but
            inline responses won't carry the correct media type.
        account: Optional account selector (name or email). Omit to
            use the user's default account.
    """
    try:
        if filename and mime_type:
            # Fast + reliable path: caller already has the metadata
            # (from read_email). Skip the server-side lookup, which
            # is unreliable because Gmail rotates attachment IDs
            # across messages.get calls.
            fetched = mail.get_attachment(
                message_id, attachment_id, account=account
            )
            data = fetched["data"]
            resolved_filename = filename
            resolved_mime = mime_type
        else:
            # Fallback: server walks the message tree to recover
            # whichever piece is missing. Best-effort — Gmail's
            # rotated IDs may force a generic fallback name.
            fetched = mail.get_attachment_with_metadata(
                message_id, attachment_id, account=account
            )
            data = fetched["data"]
            resolved_filename = filename or fetched["filename"]
            resolved_mime = mime_type or fetched["mime_type"]

        result = materialize(
            data,
            name=resolved_filename,
            mime_type=resolved_mime,
            destination=destination,
            account=account,
        )
        if isinstance(result, InlinePayload):
            return inline_payload_to_blocks(result)
        return drive_upload_to_dict(result)
    except InlineTooLargeError as e:
        return {
            "success": False,
            "error": str(e),
            "size_bytes": e.size_bytes,
            "cap_bytes": e.cap_bytes,
            "retry_with": {"kind": "drive"},
        }
    except Exception as e:
        logger.error(f"Error downloading attachment: {e}")
        return {"success": False, "error": str(e)}


async def get_email_thread(
    thread_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve a full Gmail thread, including all its messages.

    Args:
        thread_id: Gmail thread ID.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with thread details and a list of simplified messages.
    """
    try:
        return mail.get_thread(thread_id=thread_id, account=account)
    except Exception as e:
        logger.error(f"Error getting email thread '{thread_id}': {e}")
        return {"error": str(e)}
