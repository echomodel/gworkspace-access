"""Gmail operations for GWSA SDK.

Provides functions for searching, reading, labeling, and sending Gmail messages.

Example usage:
    from gwsa.sdk import mail

    # Search for messages
    messages, metadata = mail.search("from:someone@example.com")

    # Read a specific message
    message = mail.read("message_id_here")

    # Add a label to a message
    mail.add_label("message_id_here", "MyLabel")

    # Send an email
    result = mail.send("recipient@example.com", "Subject", "Body text")
"""

from .service import get_gmail_service
from .search import search_messages
from .read import read_message, read_messages, get_attachment, get_thread
from .label import modify_labels, add_label, remove_label, list_labels
from .send import send_message, create_draft, reply_message

__all__ = [
    "get_gmail_service",
    "search_messages",
    "read_message",
    "read_messages",
    "get_attachment",
    "get_thread",
    "modify_labels",
    "add_label",
    "remove_label",
    "list_labels",
    "send_message",
    "create_draft",
    "reply_message",
]

# Convenience aliases
search = search_messages
read = read_message
send = send_message
reply = reply_message
