"""Gmail operations for GWSA SDK.

Provides functions for searching, reading, labeling, and sending Gmail messages.

Example usage:
    from gwsa.sdk import mail

    # Search for messages
    messages, metadata = mail.search("from:user@example.com")

    # Read a specific message
    message = mail.read("message_id_here")

    # Add and/or remove labels across one or more messages (batch, idempotent)
    mail.modify_labels(["id1", "id2"], add_labels=["MyLabel"], remove_labels=["INBOX"])

    # Send an email
    result = mail.send("test@example.com", "Subject", "Body text")
"""

from .service import get_gmail_service
from .search import search_messages
from .read import (
    read_message,
    read_messages,
    read_message_structure,
    get_attachment,
    get_attachment_with_metadata,
    get_thread,
)
from .label import modify_labels, list_labels
from .send import send_message, create_draft, reply_message, forward_message

__all__ = [
    "get_gmail_service",
    "search_messages",
    "read_message",
    "read_messages",
    "read_message_structure",
    "get_attachment",
    "get_attachment_with_metadata",
    "get_thread",
    "modify_labels",
    "list_labels",
    "send_message",
    "create_draft",
    "reply_message",
    "forward_message",
]

# Convenience aliases
search = search_messages
read = read_message
send = send_message
reply = reply_message
forward = forward_message
