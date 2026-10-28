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


async def modify_email_labels(
    message_ids: list[str],
    add: Optional[list[str]] = None,
    remove: Optional[list[str]] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Add and/or remove labels across one or more Gmail messages.

    Applies the same label delta to every message in one batch. Labels
    in ``add`` are created if missing; labels in ``remove`` that don't
    exist are ignored. The operation is idempotent — adding a label
    already present or removing one already absent is a no-op, so each
    message converges to the desired state without per-message failures.

    Use this for both single-message and bulk changes (e.g. mass-archive
    by removing the ``INBOX`` label from many messages at once). A single
    message is just a one-element ``message_ids`` list.

    Args:
        message_ids: Gmail message IDs to modify.
        add: Label names to ensure present (e.g. ["ToReview"]).
        remove: Label names to ensure absent (e.g. ["INBOX"] to archive).
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict with ``success``, ``count``, ``message_ids``, ``added``,
        and ``removed``.
    """
    try:
        result = mail.modify_labels(
            message_ids, add_labels=add, remove_labels=remove, account=account
        )
        return {
            "success": True,
            "count": result["count"],
            "message_ids": result["message_ids"],
            "added": result["added"],
            "removed": result["removed"],
        }
    except Exception as e:
        logger.error(f"Error modifying labels: {e}")
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
    body: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Send a new standalone email via Gmail (starts a new thread).

    SAFETY / DRAFT-FIRST POLICY:
    - By default, ALWAYS prefer creating a draft in Gmail (using
      ``create_email_draft`` for new threads or ``reply_email(..., as_draft=True)``
      for replies) rather than sending an email directly.
    - NEVER call ``send_email`` to send to any recipient other than the active
      Google account's own email address unless you have FIRST displayed the
      full, verbatim message body and recipient list (`to`, `cc`, `bcc`,
      `subject`) to the user and the user has explicitly verified and
      authorized sending that exact message.

    IMPORTANT: Do NOT use this tool to reply to or follow up on an existing
    email thread — doing so creates an unthreaded standalone message without
    thread history or ``In-Reply-To`` / ``References`` headers. To reply or
    follow up on an existing message, ALWAYS use ``reply_email`` instead.

    Args:
        to: Recipient email (comma-separated for multiple).
        subject: Email subject line.
        body: Optional plain-text body (``text/plain``). NEVER pass raw HTML
            tags (``<p>``, ``<b>``, ``<table>``, etc.) in ``body`` — they will
            render as literal code tags to the recipient. For HTML emails,
            pass the HTML markup in ``html_body`` (and you may omit ``body``).
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).
        html_body: Optional HTML body (``text/html``). Use this whenever the
            email contains HTML markup, bolding, lists, or tables.
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


async def list_safe_recipients(
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List approved safe recipient aliases available for send_safe_email.

    Safe recipients are configured via the ``GWSA_SAFE_RECIPIENTS`` environment
    variable (e.g. ``my-phone=1234567890@sms.example.com``) and local configuration
    file (``safe_recipients:`` mapping). The reserved aliases ``me`` and ``self``
    always resolve automatically to the active account's own email.

    Args:
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict containing:
            - ``safe_recipients``: Mapping of alias names to email addresses.
            - ``aliases``: Sorted list of valid alias strings.
    """
    try:
        recipients = mail.get_safe_recipients(account=account)
        return {
            "safe_recipients": recipients,
            "aliases": sorted(list(recipients.keys())),
        }
    except Exception as e:
        logger.error(f"Error listing safe recipients: {e}")
        return {"error": str(e)}


async def send_safe_email(
    recipient: str,
    subject: str,
    body: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Send an email strictly to a pre-approved safe recipient or alias.

    HARNESS AUTO-APPROVAL COMPLIANT:
    - Unlike ``send_email`` (which can send to any arbitrary recipient worldwide
      and should NEVER be auto-approved without user review), ``send_safe_email``
      is structurally restricted: it can ONLY send to pre-configured safe aliases
      (e.g., 'me', 'self', 'work', 'phone') or exact email addresses that already
      exist in the user's safe recipients list.
    - Omit arbitrary ``to``, ``cc``, and ``bcc`` parameters entirely to eliminate
      the risk of unintended outbound communications or prompt injection exfiltration.
    - Designed to be safely placed on 'always allow' / auto-approved lists in agent
      harnesses (Claude Code, Antigravity, or other client harnesses) for hands-free notifications,
      digests, and summaries delivered directly to the user.

    Args:
        recipient: Safe alias. When sending an email to yourself, pass 'me' (or 'self');
            this automatically resolves to your active account email. To send to another
            destination (e.g. 'my-phone'), pass an explicitly configured alias matching
            an entry in your safe recipients configuration.
        subject: Email subject line.
        body: Optional plain-text body (``text/plain``).
        html_body: Optional HTML body (``text/html``). Use this whenever the
            email contains HTML formatting, tables, or links.
        account: Optional account to send from (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``success``, ``recipient``, ``resolved_email``, ``message_id``,
        ``thread_id``, and ``message`` describing the result. On validation or
        API error returns ``{"success": False, "error": str}``.
    """
    try:
        result = mail.send_safe_message(
            recipient=recipient,
            subject=subject,
            body=body,
            html_body=html_body,
            account=account,
        )
        resolved_to = result.get("resolved_to", recipient)
        return {
            "success": True,
            "recipient": recipient,
            "resolved_email": resolved_to,
            "message_id": result.get("id"),
            "thread_id": result.get("threadId"),
            "message": f"Email sent successfully to {resolved_to} (alias: {recipient})",
        }
    except Exception as e:
        logger.error(f"Error sending safe email: {e}")
        return {"success": False, "error": str(e)}


async def reply_email(
    message_id: str,
    body: Optional[str] = None,
    include_quote: bool = True,
    as_draft: bool = True,
    html_body: Optional[str] = None,
    reply_all: bool = True,
    to: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Reply to or follow up on an existing Gmail message (creates a draft by default).

    SAFETY / DRAFT-FIRST POLICY:
    - ``as_draft`` defaults to ``True`` so replies safely create a threaded
      Gmail draft by default.
    - NEVER set ``as_draft=False`` to send a live reply to any recipient other
      than the active Google account's own email address unless you have FIRST
      displayed the full, verbatim reply body and recipients to the user and
      the user has explicitly verified and authorized sending it.

    Always use this tool (with ``as_draft=True`` for drafts) instead of
    ``create_email_draft`` or ``send_email`` whenever responding to or
    following up on an existing email thread. It automatically:
    - attaches the reply/draft to the existing ``threadId`` with proper
      ``In-Reply-To`` and chained ``References`` headers,
    - quotes the original message below your reply (with inline ``cid:``
      images preserved) when ``include_quote=True``, and
    - resolves recipients for ``reply_all=True`` (preserving other ``To``
      and ``Cc`` addresses while excluding the active account's own email,
      and targeting the original recipients when following up on a message
      sent by the active account itself).

    Tip: When replying to a multi-message thread, call ``get_email_thread``
    first and pass the latest message's ID (``messages[-1]["id"]``) as
    ``message_id`` so the full conversation history is quoted.

    Args:
        message_id: Gmail message ID to reply to (typically the latest
            message in the thread, ``messages[-1]["id"]``).
        body: Optional plain-text reply body (``text/plain``). NEVER pass raw
            HTML tags in ``body`` — pass HTML markup in ``html_body`` instead
            (and you may omit ``body``). Do NOT manually duplicate the quoted
            thread history when ``include_quote=True``.
        include_quote: Include quoted original message (default True).
        as_draft: Create a threaded reply draft instead of sending
            (default True). Only set False after showing the verbatim reply
            to the user and receiving explicit authorization to send.
        html_body: Optional HTML body (``text/html``) of the reply. Use this
            whenever the reply contains HTML markup, bolding, lists, or
            tables. If ``include_quote`` is True, this HTML content is
            prepended above the quoted original.
        reply_all: If True (default), include all other original ``To`` and
            ``Cc`` recipients (excluding the active user's own address). If
            False, reply only to the sender.
        to: Optional explicit ``To`` override (comma-separated).
        cc: Optional explicit ``Cc`` override (comma-separated).
        bcc: Optional ``Bcc`` recipients (comma-separated).
        account: Optional account selector (name or email). Omit to
            reply as the user's default account.

    Returns:
        Dict with ``success``, ``id``, ``thread_id``, ``to``, ``cc``,
        ``subject``, ``is_draft``, and ``message``.
    """
    try:
        result = mail.reply_message(
            reply_to_message_id=message_id,
            body=body,
            include_quote=include_quote,
            as_draft=as_draft,
            html_body=html_body,
            reply_all=reply_all,
            to=to,
            cc=cc,
            bcc=bcc,
            account=account,
        )
        return {
            "success": True,
            "id": result.get("id"),
            "thread_id": result.get("threadId"),
            "to": result.get("to"),
            "cc": result.get("cc"),
            "subject": result.get("subject"),
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


async def forward_email(
    message_id: str,
    to: str,
    note: Optional[str] = None,
    html_note: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    as_draft: bool = True,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Forward a Gmail message with full MIME fidelity (creates a draft by default).

    SAFETY / DRAFT-FIRST POLICY:
    - ``as_draft`` defaults to ``True`` so forwards safely create a Gmail
      draft by default.
    - NEVER set ``as_draft=False`` to send a live forward to any recipient
      other than the active Google account's own email address unless you have
      FIRST displayed the full, verbatim note and recipients to the user and
      the user has explicitly verified and authorized sending it.

    Rebuilds the forward from the source's raw MIME, preserving every
    regular attachment byte-for-byte and every inline ``cid:`` image
    with its original Content-ID (so the quoted html still renders),
    plus both html and plain-text body alternatives. The caller's
    ``note`` / ``html_note`` is prepended above the forwarded content.
    A forward starts a new thread.

    Args:
        message_id: Gmail message ID to forward (from ``search_emails``).
        to: Recipient(s), comma-separated.
        note: Optional plain-text note prepended above the forward.
        html_note: Optional html note used as the html lead-in when the
            source has an html body.
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).
        as_draft: Create a draft instead of sending (default True). Only set
            False after showing the verbatim message to the user and receiving
            explicit authorization to send.
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict with ``success``, ``id``, ``thread_id`` (when sent),
        ``is_draft``, and ``message``.
    """
    try:
        result = mail.forward_message(
            message_id=message_id,
            to=to,
            note=note,
            html_note=html_note,
            cc=cc,
            bcc=bcc,
            as_draft=as_draft,
            account=account,
        )
        return {
            "success": True,
            "id": result.get("id"),
            "thread_id": result.get("threadId"),
            "is_draft": result.get("is_draft", False),
            "message": (
                "Forward draft created"
                if result.get("is_draft")
                else f"Message forwarded successfully to {to}"
            ),
        }
    except Exception as e:
        logger.error(f"Error forwarding email: {e}")
        return {"success": False, "error": str(e)}


async def read_email_structure(
    message_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Read a message's full per-part MIME structure.

    Unlike ``read_email`` (decoded body + flat attachment list), this
    surfaces, per non-body part: ``mime_type``, ``content_id``,
    ``disposition`` (inline vs attachment), ``filename``, ``size``, and
    ``cid_referenced`` (whether the html body points at the part via a
    ``cid:`` reference). Use when you need the structure behind a
    faithful forward/reply rebuild rather than just the readable body.

    Args:
        message_id: Gmail message ID (from ``search_emails``).
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict with header fields, ``body`` (text/html), ``parts``,
        ``inline_count``, and ``attachment_count``. On error returns
        ``{"error": str}``.
    """
    try:
        return mail.read_message_structure(message_id, account=account)
    except Exception as e:
        logger.error(f"Error reading email structure: {e}")
        return {"error": str(e)}


async def create_email_draft(
    to: str,
    subject: str,
    body: Optional[str] = None,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html_body: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new standalone Gmail draft (starts a new thread).

    Preferred default over ``send_email`` whenever preparing a new standalone
    email to another recipient so the user can inspect and send it from Gmail.

    IMPORTANT: Do NOT use this tool to draft a reply or follow-up to an
    existing email or thread — doing so creates an unthreaded standalone
    draft that loses ``threadId``, ``In-Reply-To`` / ``References`` headers,
    and the quoted conversation history. To draft a reply or follow-up to
    an existing message (including your own sent message), ALWAYS use
    ``reply_email(message_id=..., as_draft=True)`` instead.

    Args:
        to: Recipient email (comma-separated for multiple).
        subject: Email subject line.
        body: Optional plain-text body (``text/plain``). NEVER pass raw HTML
            tags (``<p>``, ``<b>``, ``<table>``, etc.) in ``body`` — they will
            render as literal code tags to the recipient. For HTML emails,
            pass the HTML markup in ``html_body`` (and you may omit ``body``).
        cc: Optional CC recipients (comma-separated).
        bcc: Optional BCC recipients (comma-separated).
        html_body: Optional HTML body (``text/html``). Use this whenever the
            draft contains HTML markup, bolding, lists, or tables.
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
) -> Any:
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
    """Retrieve a full Gmail thread, including all its messages in chronological order.

    Messages in ``messages`` are ordered oldest-first (``messages[0]`` is the
    initial message; ``messages[-1]`` is the most recent message). When
    replying to a thread via ``reply_email``, pass ``messages[-1]["id"]`` as
    ``message_id`` so the reply quotes and chains the latest message in the
    conversation.

    Args:
        thread_id: Gmail thread ID.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``id``, ``messageCount``, and ``messages`` (each with
        ``id``, ``messageId``, ``subject``, ``from``, ``to``, ``cc``,
        ``date``, and ``snippet``).
    """
    try:
        return mail.get_thread(thread_id=thread_id, account=account)
    except Exception as e:
        logger.error(f"Error getting email thread '{thread_id}': {e}")
        return {"error": str(e)}


async def list_email_filters(
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List the account's Gmail filters (Gmail ``settings.filters.list``).

    A Gmail filter is a saved rule Gmail applies to mail as it arrives:
    ``criteria`` (sender, recipient, subject, search query, …) and an
    ``action`` (labels added or removed, forwarding). Filters are how
    "always archive mail from X" stays true without re-triaging; they do
    not touch mail already in the mailbox.

    Each filter comes back with its ``id`` (needed by
    ``delete_email_filter``), ``criteria`` (the Gmail API fields that are
    set: ``from``, ``to``, ``subject``, ``query``, ``negatedQuery``,
    ``hasAttachment``, ``size``, ``sizeComparison``), ``action`` with
    label *names* (``add_labels``, ``remove_labels``, ``forward``; the raw
    ids are in ``add_label_ids`` / ``remove_label_ids``), and a one-line
    ``summary`` such as ``from:jira@example.com → archive, mark read``.

    Args:
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict with ``filters`` (list, in Gmail's order) and ``count``. On
        error returns ``{"error": str}``.
    """
    try:
        filters = mail.list_filters(account=account)
        return {"filters": filters, "count": len(filters)}
    except Exception as e:
        logger.error(f"Error listing filters: {e}")
        return {"error": str(e)}


async def create_email_filter(
    from_address: Optional[str] = None,
    to_address: Optional[str] = None,
    subject: Optional[str] = None,
    query: Optional[str] = None,
    negated_query: Optional[str] = None,
    has_attachment: Optional[bool] = None,
    size: Optional[int] = None,
    size_comparison: Optional[str] = None,
    add_labels: Optional[list[str]] = None,
    remove_labels: Optional[list[str]] = None,
    forward: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Gmail filter (Gmail ``settings.filters.create``).

    Use this when the user wants a rule that holds for future mail
    ("always archive Jira notifications", "star anything from my
    manager") rather than a one-time change. **A filter applies only to
    mail that arrives after it exists.** It never changes messages already
    in the mailbox — to clean up the current inbox as well, use
    ``search_emails`` + ``modify_email_labels`` in the same step.

    Criteria map one-to-one to the Gmail filter's criteria (at least one
    is required; all given criteria must match):

    - ``from_address`` / ``to_address``: Gmail's ``from`` / ``to`` —
      an address, a display name, or a domain (``@example.com``).
    - ``subject``: case-insensitive phrase in the subject.
    - ``query`` / ``negated_query``: Gmail search syntax that must /
      must not match (``list:dev-team``, ``has:attachment older_than:7d``).
    - ``has_attachment``: ``True`` to match only mail with attachments.
    - ``size`` + ``size_comparison``: message size in bytes with
      ``"larger"`` or ``"smaller"``; both or neither.

    Actions take label **names** (as ``modify_email_labels`` does): a
    label in ``add_labels`` is created if it does not exist; a label in
    ``remove_labels`` must exist. The common Gmail actions are system
    labels:

    - archive (skip the inbox): ``remove_labels=["INBOX"]``
    - mark as read: ``remove_labels=["UNREAD"]``
    - star: ``add_labels=["STARRED"]``
    - mark important: ``add_labels=["IMPORTANT"]``
    - delete (move to trash): ``add_labels=["TRASH"]``
    - mark as spam: ``add_labels=["SPAM"]``
    - apply a label: ``add_labels=["Receipts"]``
    - forward: ``forward="other@example.com"`` — Gmail only forwards to an
      address already added and verified in that account's Settings →
      Forwarding; otherwise Gmail rejects the filter and this tool reports
      the rejection.

    Safety: if the account already has a filter with exactly the same
    criteria, nothing is created and the existing filter is returned in
    ``existing_filter``. There is no update in the Gmail API: to change a
    filter, create the replacement first (with its new criteria or, for
    the same criteria, after deleting the old one), then
    ``delete_email_filter`` the old one by its id.

    Args:
        from_address: Sender to match (address, name, or ``@domain``).
        to_address: Recipient to match.
        subject: Subject phrase to match.
        query: Gmail search query that must match.
        negated_query: Gmail search query that must not match.
        has_attachment: Only mail with attachments.
        size: Message size threshold in bytes (with ``size_comparison``).
        size_comparison: ``"larger"`` or ``"smaller"`` (with ``size``).
        add_labels: Label names to add (created if missing).
        remove_labels: Label names to remove (must exist).
        forward: Verified address to forward matching mail to.
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict with ``success``, ``filter`` (``id``, ``criteria``, ``action``,
        ``summary``) and ``message``. On a duplicate: ``success`` false,
        ``error`` and ``existing_filter``. On any other error: ``success``
        false and ``error``, which states what the token or Gmail
        rejected and what to do.
    """
    try:
        created = mail.create_filter(
            from_address=from_address,
            to_address=to_address,
            subject=subject,
            query=query,
            negated_query=negated_query,
            has_attachment=has_attachment,
            size=size,
            size_comparison=size_comparison,
            add_labels=add_labels,
            remove_labels=remove_labels,
            forward=forward,
            account=account,
        )
        return {
            "success": True,
            "filter": created,
            "message": (
                f"Filter created ({created['summary']}). It applies to mail "
                "arriving from now on; messages already in the mailbox are "
                "unchanged."
            ),
        }
    except mail.DuplicateFilterError as e:
        return {"success": False, "error": str(e), "existing_filter": e.existing}
    except Exception as e:
        logger.error(f"Error creating filter: {e}")
        return {"success": False, "error": str(e)}


async def delete_email_filter(
    filter_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Delete one Gmail filter by id (Gmail ``settings.filters.delete``).

    Deletes exactly the filter whose ``id`` is given (from
    ``list_email_filters`` or ``create_email_filter``); there is no
    delete-by-criteria. Deleting a filter does not undo anything it did
    to mail that already arrived. To replace a filter, create the new one
    first, then delete the old one.

    Args:
        filter_id: The filter's id.
        account: Optional account selector (name or email). Omit to use
            the user's default account.

    Returns:
        Dict with ``success`` and ``id``. On error: ``success`` false and
        ``error``.
    """
    try:
        result = mail.delete_filter(filter_id, account=account)
        return {"success": True, "id": result["id"]}
    except Exception as e:
        logger.error(f"Error deleting filter: {e}")
        return {"success": False, "error": str(e)}
