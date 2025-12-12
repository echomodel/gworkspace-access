"""Gmail operations for GWSA SDK.

Provides functions for searching, reading, and labeling Gmail messages.

Example usage:
    from gwsa.sdk import mail

    # Search for messages
    messages, metadata = mail.search("from:someone@example.com")

    # Read a specific message
    message = mail.read("message_id_here")

    # Add a label to a message
    mail.add_label("message_id_here", "MyLabel")
"""

from .service import get_gmail_service
from .search import search_messages
from .read import read_message
from .label import modify_labels, add_label, remove_label, list_labels

__all__ = [
    "get_gmail_service",
    "search_messages",
    "read_message",
    "modify_labels",
    "add_label",
    "remove_label",
    "list_labels",
]

# Convenience aliases
search = search_messages
read = read_message
