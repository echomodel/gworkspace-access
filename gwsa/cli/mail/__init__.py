"""CLI mail module - re-exports from SDK."""

# Re-export from SDK mail for backwards compatibility
from gwsa.sdk.mail import (
    get_gmail_service as _get_gmail_service,
    search_messages,
    read_message,
    modify_labels,
    add_label,
    remove_label,
    list_labels,
)

# Legacy constants (for backwards compat with setup_local.py)
import os
_CONFIG_DIR = os.path.expanduser("~/.config/gworkspace-access")
USER_TOKEN_FILE = os.path.join(_CONFIG_DIR, "user_token.json")
CLIENT_SECRETS_FILE = os.path.join(_CONFIG_DIR, "client_secrets.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.file",
]

__all__ = [
    "_get_gmail_service",
    "search_messages",
    "read_message",
    "modify_labels",
    "add_label",
    "remove_label",
    "list_labels",
]
